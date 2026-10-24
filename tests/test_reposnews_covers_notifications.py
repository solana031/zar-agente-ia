"""Focused offline cover hierarchy, durable generation and notification contract."""
import io
import random
from copy import deepcopy
from unittest.mock import patch
from pathlib import Path
import pytest
from PIL import Image
from flask import Flask
from app import reposnews as rn, reposnews_covers as covers, notification_center as center, holdings, reposnews_automation as auto


def pixels(seed=1,size=(720,480)):
    rng=random.Random(seed)
    image=Image.frombytes('RGB',size,rng.randbytes(size[0]*size[1]*3))
    out=io.BytesIO();image.save(out,format='PNG');return out.getvalue()


def draft():
    return rn.article_defaults(dict(id='cover-fixture',repo='Example/tool',website='',category='Developer tools',language='Python',license='MIT',checked_at='2026-10-24',state='READY_PRIVATE',published=False,review_kind='AUTOMATED_SOURCE_REVIEW',title_es='Herramienta de ejemplo',title_en='Example tool',summary_es='Guía práctica',summary_en='Practical guide',body_es='hecho verificado '*260,body_en='verified fact '*260,sources=['https://example.org','https://docs.example.org'],seo={'es':{'canonical':rn.ORIGIN+'/es/repositorios/cover-fixture/'},'en':{'canonical':rn.ORIGIN+'/en/repositories/cover-fixture/'}}))


@pytest.fixture
def isolated(tmp_path,monkeypatch):
    monkeypatch.setenv('ZAR_DATA_DIR',str(tmp_path));rn.write({'owner':'owner','articles':[]})
    with patch('app.instagram_local_queue.status',return_value={'state':'ONLINE','session':'CONNECTED'}):yield


def test_official_wins_before_frame_and_generation(isolated):
    a=draft();blob=pixels();path=rn._path().parent/'media';path.mkdir(parents=True);name='source-'+'a'*24+'.png';(path/name).write_bytes(blob)
    with patch('app.reposnews_discovery.official_image',return_value={'image_asset':name,'image_source':'https://example.org'}),patch.object(covers,'semantic',return_value=True),patch('app.reposnews_generation.generate_article_cover') as gen:
        covers.ensure(a,{}, {'images':[{'url':'https://example.org/official.png','source':'https://example.org'}]})
    assert a['cover_provenance']['source_type']=='OFFICIAL';gen.assert_not_called()
    assert (rn._path().parent/'media'/a['image_asset']).is_file()
    assert a['cover_thumb'].endswith('-sm.webp')


def test_generated_fallback_is_cached_and_minor_edit_does_not_regenerate(isolated):
    a=draft()
    with patch('app.reposnews_generation.generate_article_cover',return_value=(pixels(),'fixture/image')) as gen,patch.object(covers,'semantic',return_value=True):
        covers.ensure(a);assert a['cover_status']=='READY'
        a['summary_en']='Small wording correction';covers.ensure(a)
        fresh=draft();covers.ensure(fresh)
        assert gen.call_count==1
    prov=a['cover_provenance'];assert prov['source_type']=='GENERATED'
    for key in ('generator','generated_at','article_id','revision','fingerprint'):assert prov[key]
    assert fresh['image_asset']==a['image_asset']


def test_good_real_cover_never_generates(isolated):
    a=draft();a['image_asset']='fastapi-official.png'
    with patch('app.reposnews_generation.generate_article_cover') as gen:
        covers.ensure(a);covers.ensure(a)
    gen.assert_not_called();assert a['cover_status']=='READY'


def test_failure_retries_are_bounded_and_keep_complete_text(isolated):
    a=draft()
    with patch('app.reposnews_generation.generate_article_cover',side_effect=ValueError('COVER_PROVIDER_503')) as gen:
        covers.ensure(a);covers.ensure(a);assert gen.call_count==1
        a['cover_job']['retry_after']=0;covers.ensure(a)
        a['cover_job']['retry_after']=0;covers.ensure(a)
    assert gen.call_count==2;assert a['cover_status']=='COVER_GENERATION_FAILED';assert auto.complete(a)


def test_blank_tiny_extreme_aspect_rejected():
    for size in ((90,90),(1200,80),(400,350)):
        assert not covers.quality(pixels(size=size))['valid']
    output=io.BytesIO();Image.new('RGB',(1280,720),'gray').save(output,format='PNG')
    assert not covers.quality(output.getvalue())['valid']


def test_prompt_excludes_private_inputs_and_credentials():
    a=draft();a.update(private_dm='PRIVATE DM',access_token='SECRET',debug='DEBUG',summary_en='Contact private@example.test api_key=SECRET ghp_123456789abcdef',body_en='Bearer sensitivevalue')
    prompt=covers.context(a)['prompt']
    for forbidden in ('PRIVATE DM','SECRET','DEBUG','private@example.test','sensitivevalue','ghp_123456789abcdef'):assert forbidden not in prompt


def test_pending_drafts_are_actionable_once_and_stale_revision_resolves(isolated):
    a=draft();a['image_asset']='fastapi-official.png';rn.write({'owner':'owner','articles':[a]})
    first=center.view('owner');second=center.view('owner')
    assert len(first['items'])==len(second['items'])==1
    note=first['items'][0];assert note['category']=='REPOSNEWS' and note['repos_filter']=='PARA PUBLICAR'
    assert note['article']['approval_request'];assert note['article']['cover']
    assert first['counts']['REQUIEREN ACCIÓN']==1
    data=rn.read();data['articles'][0]['title_es']='Revisión nueva';auto.revoke(data['articles'][0]);rn.write(data)
    notes=center.view('owner')['items'];assert len(notes)==2
    assert sum(n['completed'] for n in notes)==1
    assert len({n['id'] for n in center.view('owner')['items']})==2
    data=rn.read();data['articles'][0].update(state='CANCELLED',status='CANCELLED');rn.write(data)
    assert all(n['completed'] for n in center.view('owner')['items'])


def test_private_cover_media_is_not_public_until_snapshot_approval(isolated):
    a=draft();covers.persist(a,pixels(),'GENERATED',generator='fixture');rn.write({'owner':'owner','articles':[a]})
    app=Flask(__name__);app.before_request(rn.public_dispatch);client=app.test_client()
    assert client.get(a['cover_url'],base_url=rn.ORIGIN).status_code==404
    assert client.get(a['cover_thumb'],base_url=rn.ORIGIN).status_code==404
    a.update(published=True,published_snapshot=deepcopy(a));rn.write({'owner':'owner','articles':[a]})
    assert client.get(a['cover_url'],base_url=rn.ORIGIN).status_code==200
    assert client.get(a['cover_thumb'],base_url=rn.ORIGIN).content_type=='image/webp'


def test_published_cover_repair_is_only_a_private_proposal(isolated):
    a=draft();a.update(published=True,state='PUBLISHED');a['published_snapshot']=deepcopy(a)
    rn.write({'owner':'owner','articles':[a]});before=deepcopy(rn.read()['articles'][0]['published_snapshot'])
    def resolve(article,*args):return covers.persist(article,pixels(),'GENERATED',generator='fixture')
    with patch.object(covers,'ensure',side_effect=resolve):covers.tick()
    data=rn.read();assert data['articles'][0]['published_snapshot']==before
    assert len(data['article_revisions'])==1;assert data['article_revisions'][0]['approval_status']=='PENDING'


def test_generation_provider_uses_configured_image_route_without_private_article(isolated):
    import base64
    from unittest.mock import Mock
    from app.reposnews_generation import generate_article_cover
    response=Mock(ok=True);response.json.return_value={'candidates':[{'content':{'parts':[{'inlineData':{'mimeType':'image/png','data':base64.b64encode(pixels()).decode()}}]}}]}
    with patch('app.web_search._gemini_key',return_value='fixture-key'),patch('app.model_router.model_for',return_value='fixture-image'),patch('app.reposnews_generation.requests.post',return_value=response) as post:
        blob,provider=generate_article_cover({'private_dm':'NEVER SEND'}, {'prompt':'safe editorial prompt'})
    assert blob and provider=='Gemini/fixture-image'
    assert post.call_args.kwargs['json']['generationConfig']['imageConfig']['aspectRatio']=='16:9'
    assert 'NEVER SEND' not in str(post.call_args.kwargs['json'])


def test_ready_private_waits_for_cover_then_notifies_without_publication(isolated):
    from app import reposnews_inbox as inbox
    a=draft();item='a'*24
    rn.write({'owner':'owner','articles':[],'instagram_inbox':[{'id':item,'source_url':'https://www.instagram.com/reel/fixture/','status':'ASSETS','research_package':{'images':[]}}]})
    def waiting(article,*args):article['cover_status']='GENERATING';return article
    with patch('app.reposnews_assets.prepare'),patch.object(covers,'ensure',side_effect=waiting):inbox.store_ready(item,a)
    data=rn.read();assert data['articles'][0]['state']=='DRAFT';assert data['instagram_inbox'][0]['status']=='COVER_PENDING'
    assert not data.get('editorial_notifications')
    def finish(article,*args):return covers.persist(article,pixels(),'GENERATED',generator='fixture')
    with patch.object(covers,'ensure',side_effect=finish):covers.tick()
    data=rn.read();assert data['articles'][0]['state']=='READY_PRIVATE';assert not data['articles'][0]['published']
    notes=center.view('owner')['items'];ready=[n for n in notes if n['type']=='ARTICLE_READY']
    assert len(ready)==1;assert ready[0]['repos_filter']=='PARA PUBLICAR';assert ready[0]['article']['cover']
    assert ready[0]['article']['approval_request']


def test_missing_cover_cannot_pass_publication_gate_even_with_exact_approval(isolated):
    a=draft();a.update(approval_status='APPROVED_BY_USER',approval={'owner':'owner','revision':auto.revision(a),'at':'2026-10-24'})
    with pytest.raises(ValueError,match='VALID_ARTICLE_COVER_REQUIRED'):auto.gate(a,'owner')
    a['cover_status']='COVER_GENERATION_FAILED';assert auto.reviewable(a)
    with pytest.raises(ValueError,match='VALID_ARTICLE_COVER_REQUIRED'):auto.gate(a,'owner')


def test_notification_diagnostics_do_not_expose_credentials(isolated):
    center.emit('owner','ARTICLE_COVER_FAILED','safe-error','Error','Bearer private_value','/accounts',details={'access_token':'private_value','headers':{'authorization':'secret'},'stack_trace':'private trace','status':'FAILED'})
    payload=center.view('owner')
    assert 'private_value' not in str(payload);assert 'private trace' not in str(payload)
