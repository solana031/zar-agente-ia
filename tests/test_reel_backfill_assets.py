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


def test_pending_update_keeps_its_verified_match_before_public_approval(context):
    data=rn.read();row=data['instagram_inbox'][0]
    row.update(source_url='https://www.instagram.com/reel/NewSource/',status='ARTICLE_UPDATE_DRAFT',linked_article_id=data['articles'][0]['id'])
    before=copy.deepcopy(data['articles'])
    entry=next(e for e in history.index(data) if 'NewSource' in e['permalink'])
    assert entry['linked_article_ids']==[data['articles'][0]['id']]
    assert data['articles']==before


def test_post_and_reel_paths_for_same_shortcode_have_one_history_entry(context):
    data=rn.read();data['instagram_inbox'].append(dict(data['instagram_inbox'][0],id='b'*24,source_url='https://www.instagram.com/p/Original/?igsh=tracking'))
    entries=history.index(data)
    assert len(entries)==1;assert len(entries[0]['item_ids'])==2
    assert history.summary(data)['DUPLICATES_AVOIDED']==1


def test_duplicate_unresolved_record_cannot_erase_a_completed_article(context):
    data=rn.read();url=data['instagram_inbox'][0]['source_url'];created=data['instagram_inbox'][0]
    created['backfill_decision']='CREATE_NEW'
    data['historical_reel_index']=[{'permalink':url,'state':'COMPLETED','decision':'ARTICLE_CREATED','active_item_id':created['id']},
        {'permalink':url.replace('/reel/','/p/'),'state':'COMPLETED','decision':'NEEDS_DISAMBIGUATION','active_item_id':'b'*24}]
    entry=history.index(data)[0]
    assert entry['decision']=='ARTICLE_CREATED';assert entry['active_item_id']==created['id']
    entry['decision']='NEEDS_DISAMBIGUATION'
    assert history.index(data)[0]['decision']=='ARTICLE_CREATED'


def test_existing_project_clarification_is_reused_for_service_research():
    from app.reposnews_discovery import evidence
    row={'clarified_project':'Example Cloud','research_package':{'sources':['https://examplecloud.org/','https://docs.examplecloud.org/']}}
    result=evidence(row,{'project_names':['Other tool']},{},{})
    assert result['project_names']==['Example Cloud'];assert 'https://examplecloud.org/' in result['outbound_links']


def test_backfill_queues_only_one_and_preserves_existing_article(context):
    before=copy.deepcopy(rn.read()['articles'])
    with patch('app.reposnews_inbox.start_worker'):history.start('owner')
    history.tick();history.tick();data=rn.read()
    assert sum(e['state']=='PROCESSING' for e in data['historical_reel_index'])==1
    assert data['articles']==before;assert data['instagram_inbox'][0]['asset_refresh']
    assert history.summary(data)['concurrency']==1


def test_interrupted_asset_refresh_reclaims_expired_worker_lease(context):
    from app.instagram_local_queue import enqueue_pending
    data=rn.read();row=data['instagram_inbox'][0]
    row.update(status='TRANSCRIBING',processing_state='TRANSCRIBING',asset_refresh=True,local_job=True,local_lease=0,local_worker_done=False,local_media_received=False)
    before=copy.deepcopy(data['articles'])
    enqueue_pending(data)
    assert row['status']=='WAITING_LOCAL_WORKER';assert data['articles']==before
    row.update(asset_refresh=False,status='TRANSCRIBING')
    enqueue_pending(data)
    assert row['status']=='TRANSCRIBING'


def test_match_identity_ignores_title_and_normalizes_repo(context):
    data=rn.read();candidate=article();candidate['title_es']='Otro título';candidate['repository_url']='https://github.com/example/tool/'
    assert revisions.match(data,candidate)['id']=='example-tool'
    candidate.update(repo='other/project',repository_url='https://github.com/other/project',website='https://other.example')
    candidate['title_es']=data['articles'][0]['title_es']
    assert revisions.match(data,candidate) is None


def test_same_evidence_records_no_change_without_model_or_duplicate(context):
    a,row=context;data=rn.read();row.update(error='OLD_FAILURE',error_diagnostic={'code':'OLD_FAILURE'},error_history=[{'code':'OLD_FAILURE'}])
    with patch('app.reposnews_generation.generate_json') as model:assert revisions.consider(data,row,article())
    model.assert_not_called();assert row['status']=='NO_CHANGE';assert len(data['articles'])==1
    assert row['error']=='';assert row['error_diagnostic']=={};assert row['error_history']==[{'code':'OLD_FAILURE'}]


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


def test_exact_user_approval_updates_same_published_urls(context):
    a,row=context;data=rn.read();old=data['articles'][0];old.update(published=True,state='PUBLISHED',published_snapshot=copy.deepcopy(old))
    data.update(legal={'controller':'Fixture','privacy_contact':'fixture@example.test','activity_mode':'NONCOMMERCIAL','entity_type':'PERSON','processing_basis':'Fixture','retention':'Fixture','providers_reviewed':True},legal_reviewed=True)
    row=dict(row,source_url='https://www.instagram.com/reel/NewOfficialRelease/')
    candidate=article();candidate['body_es']+=' actualización verificada'
    with patch('app.reposnews_generation.generate_json',return_value={'relevant':True,'change_summary':'Release oficial'}):revisions.consider(data,row,candidate)
    rn.write(data);r=data['article_revisions'][0];app=Flask(__name__);app.secret_key='fixture'
    with app.test_request_context():
        from flask import session
        session['zar_auth']=True
        with patch('app.jev_decision.proposal',return_value={'decision':'ALLOW','id':'fixture'}),patch('app.jev_decision.decision_state'):
            result=revisions.decide('owner',{'id':r['article_revision_id'],'decision':'ACTUALIZAR','approval_request':revisions.token('owner',r)})
    after=rn.read();assert result['state']=='APPLIED';assert len(after['articles'])==1
    assert after['articles'][0]['id']==a['id'];assert after['articles'][0]['seo']==a['seo']
    assert after['articles'][0]['published_snapshot']['body_es']==candidate['body_es']
    assert after['articles'][0]['approval_status']=='APPROVED_BY_USER'


def test_existing_entities_are_hints_and_creator_alone_is_not_identity(context):
    from app.reposnews_entity_evidence import hints
    data=rn.read();row=data['instagram_inbox'][0];row['creator']='same-author';row['source_url']='https://www.instagram.com/reel/Unknown/'
    data['instagram_inbox'].append(dict(row,id='other',analysis={'website':'https://example.org'}))
    assert hints(data,row,{'text':'An interesting product'})['status']=='NO_MATCH'
    row['visual_assets']=[{'asset':'same-frame.jpg'}];data['instagram_inbox'][1]['visual_assets']=row['visual_assets']
    result=hints(data,row,{'text':'Unclear video'})
    assert result['status']=='UNIQUE_HINT';assert result['verified_facts'] is False
    assert result['candidates'][0]['corroborating_reels']==['other']
    result=hints(data,row,{'text':'https://example.org','project_names':['Tool']})
    assert result['status']=='UNIQUE_HINT'
    data['articles'].append(dict(data['articles'][0],id='ambiguous-tool'))
    assert hints(data,row,{'text':'https://example.org'})['status']=='AMBIGUOUS_HINTS'


def test_same_reel_provenance_identifies_an_existing_entity_without_inventing_facts(context):
    from app.reposnews_entity_evidence import hints
    data=rn.read();row=data['instagram_inbox'][0];row['source_url']=row['source_url'].replace('/reel/','/p/')
    result=hints(data,row,{'text':'Name unclear'})
    assert result['status']=='UNIQUE_HINT';assert result['candidates'][0]['evidence']==['EXACT_REEL_PROVENANCE']
    assert result['verified_facts'] is False


def test_compound_existing_name_survives_a_truncated_local_hint(context):
    from app.reposnews_entity_evidence import hints
    data=rn.read();data['articles'][0].update(repo='official/openmontage',repository_url='https://github.com/official/openmontage')
    row={'id':'new-reel','source_url':'https://www.instagram.com/reel/New/'}
    result=hints(data,row,{'project_names':['open'],'text':"It's called Open Montage. The other video model is incidental."})
    self_match=result['candidates'][0]
    assert result['status']=='UNIQUE_HINT';assert self_match['repo']=='official/openmontage';assert result['verified_facts'] is False


def test_explicit_reprocess_can_reuse_complete_media_without_redownloading(context):
    data=rn.read();row=data['instagram_inbox'][0]
    row.update(status='NEEDS_DISAMBIGUATION',local_worker_done=True,visual_assets=[{'asset':'frame.jpg'}],asset_quality_version=2)
    entry=history.index(data)[0];entry.update(state='COMPLETED',decision='NEEDS_DISAMBIGUATION',active_item_id=row['id']);rn.write(data)
    with patch('app.reposnews_inbox.start_worker'):history.start('owner',reprocess_unresolved=True,reuse_media=True)
    history.tick();row=rn.read()['instagram_inbox'][0]
    assert row['status']=='RECEIVED';assert row['local_worker_done'] is True;assert row['visual_assets']==[{'asset':'frame.jpg'}]


def test_reprocess_fetches_current_sources_once_then_reuses_its_own_checkpoint(context):
    from app import reposnews_inbox as inbox
    data=rn.read();row=data['instagram_inbox'][0]
    old={'repo':'Example/Tool','metadata':{},'readme':'Old material','sources':['https://example.org'],'verified_at':'old-date'}
    fresh=dict(old,readme='Current material',verified_at='today')
    row.update(status='RECEIVED',caption='https://github.com/Example/Tool',local_worker_done=True,reprocess_round='new-round',research_package=old)
    rn.write(data)
    with patch('app.jev_decision.proposal',return_value={'decision':'ALLOW'}),patch.object(inbox,'research',return_value=fresh) as research,patch.object(inbox,'build',side_effect=[ValueError('DRAFT_TOO_SHORT'),article()]) as build,patch.object(inbox,'store_ready') as store:
        inbox.process(row['id']);inbox.process(row['id'])
    research.assert_called_once();assert build.call_args_list[0].args[0]==fresh;assert build.call_args_list[1].args[0]==fresh
    store.assert_called_once();assert rn.read()['instagram_inbox'][0]['research_reprocess_round']=='new-round'


def test_known_source_failure_recovery_is_once_bounded_and_keeps_articles(context):
    data=rn.read();original=copy.deepcopy(data['articles']);row=data['instagram_inbox'][0]
    row.update(status='FAILED_SOURCE',error='OFFICIAL_SOURCES_UNVERIFIED',local_worker_done=True,visual_assets=[{'asset':'frame.jpg'}],asset_quality_version=2)
    entry=history.index(data)[0];entry.update(state='COMPLETED',decision='FAILED',active_item_id=row['id']);rn.write(data)
    history.repair_known_source_failures();history.tick();data=rn.read();row=data['instagram_inbox'][0]
    assert row['provenance_recovery_v3'] is True;assert row['attempt_limit']==row['attempts']+2;assert row['status']=='RECEIVED'
    assert data['articles']==original
    data['historical_reel_index'][0].update(state='COMPLETED',decision='FAILED');rn.write(data)
    history.repair_known_source_failures();assert rn.read()['historical_reel_index'][0]['state']=='COMPLETED'


def test_explicit_reprocess_preserves_completed_work_and_queues_one(context):
    data=rn.read();original=copy.deepcopy(data['articles'])
    data['instagram_inbox'][0]['asset_quality_version']=2
    for i,status in enumerate(['NEEDS_DISAMBIGUATION','FAILED_SOURCE']):
        data['instagram_inbox'].append(dict(data['instagram_inbox'][0],id=str(i)*24,source_url='https://www.instagram.com/reel/Pending'+str(i)+'/',status=status,article_id=None))
    entries=history.index(data)
    for entry in entries:entry.update(state='COMPLETED',decision='ARTICLE_CREATED' if 'Original' in entry['permalink'] else 'NEEDS_DISAMBIGUATION' if 'Pending0' in entry['permalink'] else 'FAILED')
    rn.write(data)
    with patch('app.reposnews_inbox.start_worker'):history.start('owner',reprocess_unresolved=True)
    data=rn.read();assert len([e for e in data['historical_reel_index'] if e['state']=='PENDING'])==2
    history.tick();history.tick();data=rn.read()
    assert len([e for e in data['historical_reel_index'] if e['state']=='PROCESSING'])==1
    queued=[r for r in data['instagram_inbox'] if r.get('reprocess_round')]
    assert len(queued)==1;assert queued[0]['reprocess_attempt_budget']==3
    assert data['articles']==original


def test_context_visuals_belong_to_the_selected_section_and_escape_caption():
    a={'body_es':'## Cómo funciona\nDashboard.\n## Integración\nCódigo.','assets':[
        {'role':'HERO_FRAME','url':'/media/reposnews/source-'+'0'*24+'.png'},
        {'role':'ARTICLE_FRAME_1','section_es':'Cómo funciona','url':'/media/reposnews/source-'+'1'*24+'.png','caption_es':'<script>bad</script>'},
        {'role':'ARTICLE_FRAME_2','section_es':'Integración','url':'/media/reposnews/source-'+'2'*24+'.png'},
        {'role':'ARTICLE_FRAME_3','url':'javascript:alert(1)'}]}
    rendered=str(rn.article_body_html(a,'es'))
    assert rendered.index('1'*24)<rendered.index('Integración')<rendered.index('2'*24)
    assert '0'*24 not in rendered;assert '<script>' not in rendered;assert 'javascript:' not in rendered
    assert rendered.count('<figure')==2


def test_unavailable_visual_model_does_not_blindly_select_frames(context):
    a,row=context;folder=rn._path().parent/'private-assets'/row['id'];folder.mkdir(parents=True)
    (folder/'one.jpg').write_bytes(noise());row['visual_assets']=[{'asset':'one.jpg'}]
    with patch('app.reposnews_generation.generate_json',side_effect=ValueError('AI_PROVIDER_503')),patch('app.reposnews_discovery.official_image',return_value={}):assets.prepare(row,a,{})
    assert a['contextual_asset_status']=='LIMITED';assert not any(x.get('kind')=='REEL_FRAME' for x in a['assets'])


def test_reel_cover_is_not_labelled_as_an_official_project_image(context):
    from pathlib import Path
    a,_=context;a.update(image_kind='REEL_FRAME',image_asset='source-'+'0'*24+'.png')
    app=Flask(__name__,template_folder=str(Path(__file__).resolve().parents[1]/'app/templates'))
    with app.test_request_context(),patch.object(rn,'read',return_value={'articles':[a]}),patch.object(rn,'public_legal_profile',return_value={}),patch.object(rn,'legal_status',return_value={'status':'DRAFT'}):
        assert 'Fotograma del Reel original' in rn.render('es',a['id'],True)
        assert 'Original Reel frame' in rn.render('en',a['id'],True)


def test_official_hero_competes_with_contextual_reel_frame(context):
    a,row=context;a.update(body_es='## Cómo funciona\nTexto.',body_en='## How it works\nText.')
    private=rn._path().parent/'private-assets'/row['id'];private.mkdir(parents=True);(private/'ui.jpg').write_bytes(noise())
    row['visual_assets']=[{'asset':'ui.jpg','frame_timestamp':12}]
    media=rn._path().parent/'media';media.mkdir();(media/'official.png').write_bytes(noise(2))
    result={'selected':[1,0],'placements':[{'index':0,'section_es':'Cómo funciona','section_en':'How it works','caption_es':'Panel del producto','caption_en':'Product dashboard'}]}
    with patch('app.reposnews_discovery.official_image',return_value={'image_asset':'official.png','image_source':'https://example.org'}),patch('app.reposnews_generation.generate_json',return_value=result):assets.prepare(row,a,{})
    assert a['image_kind']=='OFFICIAL_IMAGE';assert a['image_source']=='https://example.org'
    assert a['contextual_asset_status']=='READY'
    contextual=next(x for x in a['assets'] if x.get('role')=='ARTICLE_FRAME_1')
    assert contextual['section_es']=='Cómo funciona';assert contextual['frame_timestamp']==12


def test_history_diagnostics_are_owner_only_and_do_not_return_package_contents(context):
    data=rn.read();row=data['instagram_inbox'][0]
    row.update(backfill=True,error='SOURCE_OR_GENERATION_FAILED',research_package={'readme':'private source body','metadata':{}},error_diagnostic={'exception_type':'KeyError','operation':'module.py:build:12'},analysis={'project_names':['Example Tool']})
    rn.write(data);app=Flask(__name__);app.secret_key='test';history.register(app,lambda:'owner');client=app.test_client()
    assert client.get('/api/reposnews/history/status').status_code==401
    with client.session_transaction() as session:session['zar_auth']=True
    response=client.get('/api/reposnews/history/status');assert response.status_code==200
    assert response.json['diagnostics'][0]['package_fields']==['metadata','readme']
    assert response.json['diagnostics'][0]['identity_evidence']['project_names']==['Example Tool']
    assert 'private source body' not in response.text
    data['owner']='another-owner';rn.write(data)
    assert client.get('/api/reposnews/history/status').status_code==403


def test_reprocessed_result_becomes_unread_in_the_same_human_action(context):
    a,row=context;approval.notify(row['id'],'NEEDS_DISAMBIGUATION')
    from app import identity_center
    state=holdings.read('owner');actions=identity_center.ensure(state)['human_actions']
    old=actions[0];old.update(read_at='yesterday',dismissed_at='yesterday');holdings.write('owner',state)
    data=rn.read();data['instagram_inbox'][0]['reprocess_round']='new-round';rn.write(data)
    approval.notify(row['id'],'NEEDS_DISAMBIGUATION')
    result=identity_center.ensure(holdings.read('owner'))['human_actions']
    assert len(result)==1;assert result[0]['id']==old['id'];assert result[0]['read_at'] is None;assert result[0]['dismissed_at'] is None


def test_old_human_question_is_processing_then_completed_when_reel_resolves(context):
    from app import notification_center as center
    a,row=context;approval.notify(row['id'],'NEEDS_DISAMBIGUATION')
    data=rn.read();data['instagram_inbox'][0].update(status='TRANSCRIBING',reprocess_round='round');rn.write(data)
    note=next(n for n in center.view('owner')['items'] if n.get('editorial'))
    assert note['processing'] is True;assert note['completed'] is False
    data=rn.read();data['instagram_inbox'][0]['status']='ARTICLE_UPDATE_DRAFT';rn.write(data)
    note=next(n for n in center.view('owner')['items'] if n.get('editorial'))
    assert note['processing'] is False;assert note['completed'] is True
