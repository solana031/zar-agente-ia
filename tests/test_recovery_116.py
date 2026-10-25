"""Health isolation, real provider failover, pagination recovery and targeted identification."""
import json
import threading
import time
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch
import pytest
from flask import Flask
from app import reposnews as rn, reposnews_covers as covers, reposnews_cover_providers as providers
from app import instagram_conversation_history as history, reposnews_ambiguity as ambiguity
from app.notification_center import reconcile_actions
from app.runtime_health import install, start_background


@pytest.fixture
def store(tmp_path,monkeypatch):
    monkeypatch.setenv('ZAR_DATA_DIR',str(tmp_path))
    rn.write({'owner':'owner','articles':[],'instagram_inbox':[]})


def test_health_bypasses_storage_network_session_and_blocked_later_hooks():
    app=Flask(__name__);install(app)
    @app.before_request
    def expensive():raise AssertionError('Health reached application initialization')
    with patch('requests.get',side_effect=AssertionError),patch.object(rn,'read',side_effect=AssertionError):
        client=app.test_client();started=time.perf_counter()
        for _ in range(3):
            response=client.get('/health');assert response.status_code==200
            assert set(response.json)<= {'status','version','commit'} and response.json['status']=='ok'
        assert time.perf_counter()-started<.5


def test_background_boot_does_not_wait_for_connectors():
    entered=threading.Event();release=threading.Event()
    def blocked():entered.set();release.wait(2)
    thread=start_background(blocked)
    try:
        assert entered.wait(.5) and thread.is_alive() and thread.daemon
        app=Flask(__name__);install(app)
        assert app.test_client().get('/health').status_code==200
    finally:release.set();thread.join(1)


def test_429_failover_does_not_retry_gemini_and_honors_retry_after(store):
    blob=providers.editorial({'repo':'code/sdk'})[0]
    error=providers.ProviderError('COVER_PROVIDER_429','1800')
    with patch('app.reposnews_generation._gemini_article_cover',side_effect=error) as gemini,patch.object(providers,'_openrouter',return_value=(blob,'OpenRouter/fixture')) as other,patch.object(covers,'semantic',return_value=True):
        for _ in range(2):assert providers.generate({'id':'x'},{'prompt':'public'})[1]=='OpenRouter/fixture'
    assert gemini.call_count==1 and other.call_count==2
    state=json.loads((rn._path().parent/'cover-provider-state.json').read_text())
    assert state['Gemini']['retry_after']>time.time()+1700
    assert state['Gemini']['error']=='COVER_PROVIDER_429'


def test_all_providers_fail_offline_cover_remains_valid_and_cached(store):
    article={'id':'offline','repo':'tool/video','category':'Video','title_en':'Video tools','summary_en':'A video pipeline'}
    with patch('app.reposnews_generation._gemini_article_cover',side_effect=providers.ProviderError('COVER_PROVIDER_429')),patch.object(providers,'_openrouter',side_effect=providers.ProviderError('COVER_PROVIDER_402')),patch.object(providers,'_comfy',side_effect=ValueError('COVER_PROVIDER_NOT_CONFIGURED')),patch.object(covers,'semantic',side_effect=AssertionError('Offline fallback called a model')):
        covers.ensure(article);assert covers.valid(article)
        prov=article['cover_provenance'];assert prov['generator']==providers.INTERNAL
        assert prov['source_type']=='GENERATED' and prov['article_id']=='offline' and prov['generated_at'] and prov['revision']
        asset=article['image_asset'];covers.ensure(article);assert article['image_asset']==asset


def test_previous_provider_backoff_or_exhaustion_cannot_leave_empty_cover(store):
    for job in ({'retry_after':time.time()+600},{'lease':time.time()+600},{'attempts':2}):
        article={'id':'blocked-'+str(len(job)),'repo':'code/sdk','cover_job':job}
        with patch('app.reposnews_generation.generate_article_cover',side_effect=AssertionError('Retry bypass')):
            covers.ensure(article);assert covers.valid(article) and article['cover_status']=='READY'


def test_internal_cover_private_preview_renders_without_false_ai_label(store):
    app=Flask(__name__,template_folder=str(Path(rn.__file__).parent/'templates'))
    article=rn.article_defaults({'id':'preview','repo':'tool/sdk','category':'Code','title_es':'Prueba','title_en':'Test',
        'summary_es':'Resumen','summary_en':'Summary','body_es':'Texto de prueba','body_en':'Test body','state':'DRAFT','published':False,
        'checked_at':'2026-10-25','cover_job':{'attempts':2}})
    covers.ensure(article);rn.write({'owner':'owner','articles':[article]})
    with app.test_request_context('/reposnews-preview/es/preview'):
        html=rn.render('es','preview',preview=True)
    assert article['cover_url'] in html and 'Ilustración editorial de ReposNews' in html
    assert 'Ilustración editorial generada con IA' not in html


def conversation():return {'data':[{'id':'c','participants':{'data':[{'id':'sender','username':'solana031'}]}}]}
def page(ids,cursor=None):return {'data':[{'id':i,'created_time':'2026-10-25T01:00:00Z','from':{'id':'other'}} for i in ids],**({'paging':{'next':'https://graph.instagram.com/edge','cursors':{'after':cursor}}} if cursor else {})}


def test_repeat_saves_checkpoint_and_resumes_previous_valid_page_not_whole_history(store):
    with patch('app.reposnews_inbox.credentials',return_value={'access_token':'fixture'}),patch('app.reposnews_inbox.sender_ids',return_value={'sender'}),patch.object(history,'_read',side_effect=[conversation(),page(['m1'],'a'),page(['m2'],'b'),page(['m3'],'b')]):
        result=history.sync('owner',force=True)
    assert result['error']=='PAGINATION_CURSOR_REPEAT'
    data=rn.read();checkpoint=data['instagram_conversation_sync']['checkpoints']['c']
    assert checkpoint['pages_completed']==3 and checkpoint['messages_seen']==3
    assert checkpoint['last_successful_cursor']=='a' and checkpoint['cursor_recovery_required']
    assert data['instagram_conversation_sync']['page_diagnostics']['messages:c']['cursor_in']=='b'
    assert result['retry_after']>time.time()+3500
    with patch('app.reposnews_inbox.credentials',return_value={'access_token':'fixture'}),patch('app.reposnews_inbox.sender_ids',return_value={'sender'}),patch.object(history.time,'time',return_value=time.time()+3601),patch.object(history,'_read',side_effect=[conversation(),page(['m2','m3'],'fresh'),page(['m4'])]) as read:
        result=history.sync('owner')
    assert result['status']=='COMPLETED' and read.call_args_list[1].args[2]['after']=='a'
    assert rn.read()['instagram_conversation_sync']['checkpoints']['c']['messages_seen']==4


def test_repeated_messages_with_changed_cursor_can_progress(store):
    progress={}
    with patch.object(history,'_read',side_effect=[page(['m'],'a'),page(['m'],'b'),page(['n'])]):
        assert len(list(history._pages('c/messages','fixture',{},progress=progress)))==3
    assert progress['new_message_count']==1


def test_rate_limit_and_invalid_cursor_are_separate(store):
    for code,message,expected in [(4,'Application request limit reached','META_HISTORY_RATE_LIMITED'),(100,'Invalid paging cursor','PAGINATION_CURSOR_INVALID')]:
        response=Mock(ok=False,status_code=403,headers={});response.json.return_value={'error':{'code':code,'message':message}}
        with patch.object(history.requests,'get',return_value=response):
            with pytest.raises(history.HistoryReadError,match=expected):history._read('c/messages','fixture',{})


def test_ambiguity_round_targets_only_unresolved_index_and_is_idempotent(store):
    data=rn.read();data['historical_reel_index']=[]
    for i in range(19):
        unresolved=i<9;identifier=f'{i:024x}'
        data['instagram_inbox'].append({'id':identifier,'status':'NEEDS_DISAMBIGUATION' if unresolved else 'PUBLISHED'})
        data['historical_reel_index'].append({'decision':'NEEDS_DISAMBIGUATION' if unresolved else 'ARTICLE_CREATED','item_ids':[identifier],'active_item_id':identifier})
    rn.write(data);job=ambiguity.start('owner');assert len(job['ids'])==9
    result={'status':'NEEDS_DISAMBIGUATION','candidates':[],'frames_examined':8}
    with patch.object(ambiguity,'identify',return_value=result) as identify:
        for _ in range(10):ambiguity.tick()
    assert identify.call_count==9 and len(rn.read()['ambiguous_reprocessing']['completed'])==9
    assert not ambiguity.start('owner')['enabled']
    assert sum(r['status']=='PUBLISHED' for r in rn.read()['instagram_inbox'])==10


def test_identity_needs_multiple_signals_and_official_proof(store):
    row={'id':'a'*24,'analysis':{'project_names':['ExactTool'],'transcript':'ExactTool does this','visual_findings':'ExactTool interface'},'visual_assets':[]}
    resolution={'status':'RESOLVED','name':'ExactTool','repo':'official/ExactTool','sources':['https://github.com/official/ExactTool']}
    data=rn.read();data['ambiguous_reprocessing']={'provider_retry_after':time.time()+600}
    with patch('app.reposnews_inbox.resolve_entity',return_value=resolution) as verify:
        assert ambiguity.identify(data,row)['status']=='AUTO_IDENTIFIED'
        row['analysis']['visual_findings']='unreadable';assert ambiguity.identify(data,row)['status']=='NEEDS_DISAMBIGUATION'
    assert verify.call_count==1


def test_cleanup_keeps_history_and_real_blockers(store):
    rows=[{'id':'old','type':'ARTICLE_FAILED','inbox_item_id':'r','status':'ACTION_REQUIRED'},
        {'id':'dupe1','notification_key':'same','status':'ACTION_REQUIRED'},
        {'id':'dupe2','notification_key':'same','status':'ACTION_REQUIRED'},
        {'id':'blocked','type':'SOCIAL_ACCOUNT_BLOCKED','entity_id':'tiktok','status':'ACTION_REQUIRED'},
        {'id':'good','type':'ACCOUNT_CONNECTION','entity_id':'youtube','created_at':'2026-10-20','status':'ACTION_REQUIRED'}]
    before=deepcopy(rows)
    assert reconcile_actions(rows,{'instagram_inbox':[{'id':'r','status':'PUBLISHED'}]}, {'youtube':{'status':'UPLOAD_READY','last_verified':'2026-10-25','human_action':None}})==3
    assert len(rows)==len(before) and rows[3]['status']=='ACTION_REQUIRED' and rows[2]['status']=='ACTION_REQUIRED'


def test_group_updates_after_identification_and_preserves_candidate_labels(store):
    from app import notification_center as center
    data=rn.read();data['ambiguous_reprocessing']={'ids':['one','two'],'completed':['one','two'],'round':ambiguity.ROUND}
    data['instagram_inbox']=[{'id':i,'status':'NEEDS_DISAMBIGUATION','expanded_identification':{'candidates':[{'candidate':'ExactTool','confidence':.45,'evidence':[{'signal':'OCR','quote':'ExactTool'}]}]}} for i in ('one','two')]
    rn.write(data)
    with patch('app.instagram_local_queue.status',return_value={'state':'ONLINE','session':'CONNECTED'}):
        first=center.view('owner');note=next(n for n in first['items'] if n['type']=='ARTICLE_IDENTIFICATION_REQUIRED')
        assert note['details']['items'][0]['candidates'][0]['candidate']=='ExactTool'
        data=rn.read();data['instagram_inbox'][0]['status']='RECEIVED';rn.write(data)
        second=center.view('owner');note=next(n for n in second['items'] if n['type']=='ARTICLE_IDENTIFICATION_REQUIRED')
        assert len(note['details']['items'])==1 and note['details']['items'][0]['id']=='two'
