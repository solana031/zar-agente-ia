import copy
import io
import random
from unittest.mock import patch
import pytest
from flask import Flask
from PIL import Image
from app import reposnews as rn,reposnews_assets as assets,reposnews_history as history,reposnews_revisions as revisions,reposnews_automation as approval,holdings


def article():
    return rn.article_defaults({'id':'example-tool','repo':'Example/Tool','repository_url':'https://github.com/Example/Tool','website':'https://example.org','category':'Tools','language':'Python','license':'MIT',
        'checked_at':'2026-10-18','state':'READY_PRIVATE','published':False,'sources':['https://example.org','https://github.com/example/tool'],
        'review_kind':'AUTOMATED_SOURCE_REVIEW','title_es':'Ejemplo','title_en':'Example','summary_es':'Guía','summary_en':'Guide',
        'body_es':'hecho verificado '*300,'body_en':'verified fact '*300,'discovery_source':'https://www.instagram.com/reel/Original/','source_reels':['https://www.instagram.com/reel/Original/']})


@pytest.fixture
def context(tmp_path,monkeypatch):
    monkeypatch.setenv('ZAR_DATA_DIR',str(tmp_path));monkeypatch.setenv('INSTAGRAM_REPOSNEWS_SENDERS','sender')
    a=article();row={'id':'a'*24,'external_id':'original','source_url':a['discovery_source'],'status':'READY_PRIVATE','article_id':a['id'],'sender':'sender','attempts':0}
    rn.write({'owner':'owner','articles':[a],'instagram_inbox':[row]})
    return a,row


def noise(seed=1):
    rng=random.Random(seed);image=Image.frombytes('L',(320,240),bytes(rng.randrange(256) for _ in range(320*240))).convert('RGB')
    out=io.BytesIO();image.save(out,format='JPEG');return out.getvalue()


def test_black_blank_blurred_and_small_frames_are_rejected():
    for size,color in [((320,240),'black'),((320,240),'white'),((320,240),'gray'),((80,80),'gray')]:
        out=io.BytesIO();Image.new('RGB',size,color).save(out,format='JPEG')
        assert not assets.inspect_image(out.getvalue())['valid']
    assert assets.inspect_image(noise())['valid']


def test_frames_deduplicate_and_keep_provenance(context):
    a,row=context;folder=rn._path().parent/'private-assets'/row['id'];folder.mkdir(parents=True)
    (folder/'one.jpg').write_bytes(noise());row['visual_assets']=[{'asset':'one.jpg','frame_timestamp':2}]*2
    with patch('app.reposnews_generation.generate_json',return_value={'selected':[0],'shows_es':'UI visible','shows_en':'Visible UI'}):assets.prepare(row,a,{})
    frames=[x for x in a['assets'] if x['kind']=='REEL_FRAME']
    assert len(frames)==1;assert a['image_kind']=='REEL_FRAME';assert a['asset_status']=='ASSETS_READY'
    for key in ['source_type','source_url','origin','timestamp','usage_note','captured_from_reel','frame_timestamp']:assert key in frames[0]
    assert frames[0]['role']=='HERO_FRAME';assert frames[0]['captured_from_reel'] is True
    assert (rn._path().parent/'media'/frames[0]['asset']).exists()


def test_failed_asset_attempts_are_honestly_limited(context):
    a,row=context
    with patch('app.reposnews_discovery.official_image',return_value={}):assets.prepare(row,a,{})
    assert a['asset_status']=='ASSETS_LIMITED';assert a['asset_attempts'];assert a['assets'][-1]['kind']=='EDITORIAL_COVER'


def test_historical_index_unifies_permalinks_not_titles(context):
    data=rn.read();data['instagram_event_history']=[{'url':data['instagram_inbox'][0]['source_url']+'?igsh=foo'}]
    data['articles'][0]['source_reels'].append('https://www.instagram.com/reel/Second/')
    assert len(history.index(data))==2
    assert len(history.index(data))==2
    assert history.summary(data)['TOTAL_REELS']==2


def test_backfill_queues_only_one_and_preserves_existing_article(context):
    before=copy.deepcopy(rn.read()['articles'])
    with patch('app.reposnews_inbox.start_worker'):history.start('owner')
    history.tick();history.tick();data=rn.read()
    assert sum(e['state']=='PROCESSING' for e in data['historical_reel_index'])==1
    assert data['articles']==before;assert data['instagram_inbox'][0]['asset_refresh']
    assert history.summary(data)['concurrency']==1


def test_match_identity_ignores_title_and_normalizes_repo(context):
    data=rn.read();candidate=article();candidate['title_es']='Otro título';candidate['repository_url']='https://github.com/example/tool/'
    assert revisions.match(data,candidate)['id']=='example-tool'
    candidate.update(repo='other/project',repository_url='https://github.com/other/project',website='https://other.example')
    candidate['title_es']=data['articles'][0]['title_es']
    assert revisions.match(data,candidate) is None


def test_same_evidence_records_no_change_without_model_or_duplicate(context):
    a,row=context;data=rn.read()
    with patch('app.reposnews_generation.generate_json') as model:assert revisions.consider(data,row,article())
    model.assert_not_called();assert row['status']=='NO_CHANGE';assert len(data['articles'])==1


def test_update_draft_preserves_live_snapshot_and_requires_exact_approval(context):
    a,row=context;data=rn.read();a=data['articles'][0];a.update(published=True,state='PUBLISHED',published_snapshot=copy.deepcopy(a));original=copy.deepcopy(a)
    row=dict(row,source_url='https://www.instagram.com/reel/NewEvidence/',analysis={'transcript':'new feature'},research_package={'sources':['https://example.org/release']})
    candidate=article();candidate['body_es']+=' nuevo dato oficial'
    with patch('app.reposnews_generation.generate_json',return_value={'relevant':True,'change_summary':'Nueva integración documentada'}):
        assert revisions.consider(data,row,candidate)
    assert data['articles'][0]==original;assert len(data['article_revisions'])==1
    r=data['article_revisions'][0];assert r['state']=='ARTICLE_UPDATE_DRAFT';assert r['diff']['UPDATED']
    rn.write(data);app=Flask(__name__);app.secret_key='fixture'
    with app.test_request_context():
        from flask import session
        session['zar_auth']=True
        with pytest.raises(ValueError,match='CURRENT_UPDATE_APPROVAL_REQUIRED'):revisions.decide('owner',{'id':r['article_revision_id'],'decision':'ACTUALIZAR'})
        proof=revisions.token('owner',r);data=rn.read();data['articles'][0]['title_es']='Human edit';rn.write(data)
        with pytest.raises(ValueError,match='BASE_ARTICLE_CHANGED'):revisions.decide('owner',{'id':r['article_revision_id'],'decision':'ACTUALIZAR','approval_request':proof})
    assert rn.read()['articles'][0]['published_snapshot']==original['published_snapshot']


def test_ignoring_update_preserves_article_and_records_history(context):
    a,row=context;data=rn.read();row=dict(row,source_url='https://www.instagram.com/reel/New/')
    with patch('app.reposnews_generation.generate_json',return_value={'relevant':True,'change_summary':'New workflow'}):revisions.consider(data,row,article())
    rn.write(data);r=data['article_revisions'][0];app=Flask(__name__);app.secret_key='test'
    with app.test_request_context():
        from flask import session
        session['zar_auth']=True
        result=revisions.decide('owner',{'id':r['article_revision_id'],'decision':'IGNORAR','approval_request':revisions.token('owner',r)})
    assert result['state']=='IGNORED';assert rn.read()['articles']==[a]
