"""Offline restrictions, bounded probes, OAuth gates and notification recovery."""
import json
from unittest.mock import Mock,patch
import pytest
from flask import Flask,session,abort,request
from app import holdings,reposnews as rn,reposnews_inbox as inbox,oauth_vault,meta_provider as meta
from app.account_connections import AccountConnectionRegistry,register

@pytest.fixture
def blocked(tmp_path,monkeypatch):
    monkeypatch.setenv('ZAR_DATA_DIR',str(tmp_path))
    monkeypatch.setenv('INSTAGRAM_ACCESS_TOKEN','expired-env-fixture')
    rn.write({'owner':'owner','articles':[{'id':'preserved'}],'instagram_callback':{'status':'ERROR','error':'IDENTITY_NOT_VERIFIED','checked_at':'2026-10-23T11:07:12+00:00','detail':{'http':400,'code':200,'message':'API access blocked.'}}})
    root=rn._path().parent
    oauth_vault.persist(root/'instagram-oauth',json.dumps({'access_token':'canonical-fixture','user_id':'123','username':'zaragente031'}),root)
    oauth_vault.persist(root/'instagram-oauth-pending',json.dumps({'keep':'untouched'}),root)
    meta.observation('owner',{'account_confirmation_required':True,'confirmation_ui_error':True,'app_status':'UNKNOWN_DASHBOARD_GATED','account_status':'DEVELOPER_CONFIRMATION_REQUIRED','support_case_status':'HUMAN_CAPTCHA_REQUIRED'})
    return root

def response(http=401,body=None):
    return Mock(ok=http<400,status_code=http,json=lambda:body if body is not None else {'error':{'code':190}})

def test_current_block_is_evidence_based_and_get_does_no_network(blocked):
    with patch.object(meta.requests,'get') as call:
        item=next(p for p in AccountConnectionRegistry('owner').view()['providers'] if p['id']=='instagram')
    call.assert_not_called()
    assert item['status']=='PROVIDER_BLOCKED' and item['account_identity']=='@zaragente031'
    assert item['reason']=='DEVELOPER_ACCOUNT_CONFIRMATION_REQUIRED'
    assert 'canonical-fixture' not in json.dumps(item)
    assert not meta.current('other')
    assert not meta.api_blocked({'code':190,'message':'expired'})
    assert not meta.api_blocked({'code':200,'message':'Missing optional permission'})

def test_expired_token_cannot_unlock_provider_or_select_env(blocked):
    before={p.name:p.read_bytes() for p in blocked.glob('instagram-oauth*')}
    with patch.object(meta.requests,'get',return_value=response()) as call,patch.object(meta.requests,'post') as post:
        result=meta.probe('owner',now=1000)
    assert call.call_count==1
    assert call.call_args.kwargs['headers']['Authorization']=='Bearer canonical-fixture'
    assert call.call_args.kwargs['allow_redirects'] is False
    post.assert_not_called()
    assert result['api_access_blocked'] and result['probe_result']=='TOKEN_INVALID_PROVIDER_STATE_UNKNOWN'
    assert meta.blocked_view('owner')['status']=='PROVIDER_BLOCKED'
    assert before=={p.name:p.read_bytes() for p in blocked.glob('instagram-oauth*')}
    assert rn.read()['articles']==[{'id':'preserved'}]

def test_daily_and_manual_backoff_survive_restarts(blocked):
    with patch.object(meta.requests,'get',return_value=response()) as call:
        meta.probe('owner',now=1000)
        meta.probe('owner',now=1001)
        meta.probe('owner',now=1002)
        assert call.call_count==1
        meta.probe('owner',manual=True,now=1003)
        meta.probe('owner',manual=True,now=1004)
        meta.probe('owner',manual=True,now=1005)
        assert call.call_count==3
        meta.probe('owner',manual=True,now=2000)
        assert call.call_count==3
        meta.probe('owner',now=1004+meta.DAY)
        assert call.call_count==4

def test_verified_identity_releases_and_enables_auth(blocked):
    registry=AccountConnectionRegistry('owner')
    registry.notification('instagram',meta.blocked_view('owner'))
    registry.notification('instagram',meta.blocked_view('owner'))
    assert len(holdings.read('owner')['identity_center']['human_actions'])==1
    with patch.object(meta.requests,'get',return_value=response(200,{'username':'zaragente031','user_id':'123'})):
        meta.daily_check('owner')
    assert not meta.blocked_view('owner')
    data=holdings.read('owner')
    assert data['account_connections']['instagram']['status']=='AUTH_REQUIRED'
    rows=data['identity_center']['human_actions']
    assert next(r for r in rows if r['title']=='META BLOQUEA INSTAGRAM')['status']=='DONE'
    assert len([r for r in rows if r['status']!='DONE'])==1

def test_wrong_identity_never_unlocks(blocked):
    with patch.object(meta.requests,'get',return_value=response(200,{'username':'other','user_id':'999'})):
        meta.probe('owner')
    assert meta.blocked_view('owner')

def test_oauth_routes_block_without_new_state_or_provider_calls(blocked):
    app=Flask(__name__);app.secret_key='fixture'
    def csrf():
        if session.get('zar_auth') is not True or request.headers.get('X-ZAR-Business-CSRF')!='fixture':abort(403)
        return 'owner'
    register(app,lambda:'owner',csrf);inbox.register(app,lambda:'owner')
    client=app.test_client()
    with client.session_transaction() as s:s['zar_auth']=True
    with patch.object(meta.requests,'get') as read,patch.object(meta.requests,'post') as write:
        for action in ('connect','reconnect'):
            r=client.post('/api/accounts/connections/instagram/'+action,json={'external':True},headers={'X-ZAR-Business-CSRF':'fixture'})
            assert r.status_code==423 and r.json['error']=='PROVIDER_BLOCKED'
        assert client.get('/api/reposnews/instagram/connect').status_code==423
    read.assert_not_called();write.assert_not_called()
    assert not list(blocked.glob('*transactions*'))

def test_notification_dedup_and_manual_action(blocked):
    registry=AccountConnectionRegistry('owner')
    for _ in range(3):registry.notification('instagram',meta.blocked_view('owner'))
    rows=holdings.read('owner')['identity_center']['human_actions']
    assert len(rows)==1 and rows[0]['title']=='META BLOQUEA INSTAGRAM'
    assert [a['label'] for a in rows[0]['actions']]==['ABRIR META','REVERIFICAR']
    assert 'reverify=instagram' in rows[0]['actions'][1]['url']

def test_daily_worker_cannot_reprobe_after_recreation(blocked):
    with patch.object(meta.requests,'get',return_value=response(400,{'error':{'code':200,'message':'API access blocked.'}})) as call:
        meta.daily_check('owner');meta.daily_check('owner')
    assert call.call_count==1
    assert holdings.read('owner')['meta_provider_diagnostic']['probe_result']=='API_ACCESS_BLOCKED'

def test_callback_detects_provider_block_without_promoting_unverified_token(blocked):
    import time
    from app import oauth_transport
    data=rn.read();data['instagram_callback']={};rn.write(data)
    data=holdings.read('owner');data.pop('meta_provider_diagnostic',None);holdings.write('owner',data)
    assert not meta.blocked_view('owner')
    before=(blocked/'instagram-oauth').read_bytes()
    app=Flask(__name__);app.secret_key='fixture';inbox.register(app,lambda:'owner')
    oauth_transport.put('state:instagram:fixture',{'value':'fixture','expires':time.time()+60,'user_id':'owner','redirect_uri':'https://zar.test/api/reposnews/instagram/callback'})
    def get(url,**kwargs):
        if url=='https://graph.instagram.com/access_token':return response(200,{'access_token':'unverified-long-fixture','expires_in':5184000})
        return response(400,{'error':{'code':200,'message':'API access blocked.'}})
    with patch.dict('os.environ',{'INSTAGRAM_APP_ID':'fixture','INSTAGRAM_APP_SECRET':'fixture'}),patch.object(inbox.requests,'post',return_value=response(200,{'access_token':'unverified-fixture','user_id':'123'})),patch.object(inbox.requests,'get',side_effect=get):
        app.test_client().get('/api/reposnews/instagram/callback?state=fixture&code=fixture')
    assert meta.blocked_view('owner')['status']=='PROVIDER_BLOCKED'
    assert rn.read()['instagram_callback']['error']=='IDENTITY_NOT_VERIFIED'
    assert (blocked/'instagram-oauth').read_bytes()==before

def test_automatic_registry_checks_share_daily_limit(blocked):
    with patch.object(meta.requests,'get',return_value=response()) as call:
        registry=AccountConnectionRegistry('owner')
        registry.reverify('instagram');registry.reverify('instagram');meta.daily_check('owner')
        assert call.call_count==1
        registry.reverify('instagram',manual=True)
        assert call.call_count==2

def test_dedup_updates_current_human_action_without_new_notification(blocked):
    registry=AccountConnectionRegistry('owner');registry.notification('instagram',meta.blocked_view('owner'))
    meta.observation('owner',{'confirmation_ui_error':False,'confirmation_flow':'HUMAN_EMAIL_CODE_REQUIRED'})
    registry.notification('instagram',meta.blocked_view('owner'))
    rows=holdings.read('owner')['identity_center']['human_actions']
    assert len(rows)==1 and 'personalmente' in rows[0]['message']

def test_confirmed_developer_can_retry_oauth_once_without_claiming_api_recovery(blocked):
    from app import oauth_transport
    meta.observation('owner',{'account_confirmation_required':False,'confirmation_flow':'COMPLETED'})
    assert not meta.oauth_recovery('owner')  # Confirmation alone is not authorization.
    meta.observation('owner',{'oauth_recovery_authorized':True})
    assert meta.blocked_view('owner')['oauth_recovery_available'] is True
    before=(blocked/'instagram-oauth').read_bytes()
    app=Flask(__name__);app.secret_key='fixture'
    register(app,lambda:'owner',lambda:'owner');inbox.register(app,lambda:'owner')
    client=app.test_client()
    with patch.dict('os.environ',{'INSTAGRAM_APP_ID':'fixture','INSTAGRAM_APP_SECRET':'fixture'}),patch.object(meta.requests,'get') as read,patch.object(meta.requests,'post') as write:
        launch=client.post('/api/accounts/connections/instagram/reconnect',json={'external':True})
        assert launch.status_code==200
        route=client.get('/api/reposnews/instagram/connect')
        assert route.status_code==302 and route.location.startswith('https://www.instagram.com/oauth/authorize?')
        assert client.get('/api/reposnews/instagram/connect').status_code==423
    read.assert_not_called();write.assert_not_called()
    assert meta.current('owner')['api_access_blocked'] is True
    assert not meta.current('owner').get('resolved_at')
    assert not meta.blocked_view('owner')['oauth_recovery_available']
    assert meta.current('owner')['oauth_recovery_prior_block']['message']=='API access blocked.'
    assert (blocked/'instagram-oauth').read_bytes()==before
    assert rn.read()['instagram_callback']['detail']['message']=='API access blocked.'

def test_recovery_callback_clears_block_only_after_canonical_identity_readback(blocked):
    import time
    from app import oauth_transport
    app=Flask(__name__);app.secret_key='fixture';inbox.register(app,lambda:'owner')
    oauth_transport.put('state:instagram:recovery',{'value':'recovery','expires':time.time()+60,'user_id':'owner','redirect_uri':'https://zar.test/api/reposnews/instagram/callback'})
    def get(url,**kwargs):
        if url=='https://graph.instagram.com/access_token':return response(200,{'access_token':'new-long-fixture','token_type':'bearer','expires_in':5184000})
        if url.endswith('/me'):return response(200,{'username':'zaragente031','user_id':'123'})
        return response(200,{'data':[]})
    with patch.dict('os.environ',{'INSTAGRAM_APP_ID':'fixture','INSTAGRAM_APP_SECRET':'fixture'}),patch.object(inbox.requests,'post',return_value=response(200,{'access_token':'new-fixture','user_id':'123','success':True})),patch.object(inbox.requests,'get',side_effect=get):
        app.test_client().get('/api/reposnews/instagram/callback?state=recovery&code=fixture')
    assert not meta.blocked_view('owner')
    assert inbox.credentials()['access_token']=='new-long-fixture'
    assert inbox.credentials()['token_class']=='LONG_LIVED'
    assert rn.read()['instagram_credential_diagnostic']['NEW_TOKEN_READBACK'] is True

def test_failed_persistence_keeps_provider_blocked(blocked):
    import time
    from app import oauth_transport
    app=Flask(__name__);app.secret_key='fixture';inbox.register(app,lambda:'owner')
    oauth_transport.put('state:instagram:failed',{'value':'failed','expires':time.time()+60,'user_id':'owner','redirect_uri':'https://zar.test/api/reposnews/instagram/callback'})
    def get(url,**kwargs):
        if url=='https://graph.instagram.com/access_token':return response(200,{'access_token':'new-long-fixture','expires_in':5184000})
        return response(200,{'username':'zaragente031','user_id':'123'})
    with patch.dict('os.environ',{'INSTAGRAM_APP_ID':'fixture','INSTAGRAM_APP_SECRET':'fixture'}),patch.object(inbox.requests,'post',return_value=response(200,{'access_token':'new-fixture','user_id':'123'})),patch.object(inbox.requests,'get',side_effect=get),patch.object(inbox,'persist_identity',side_effect=ValueError('READBACK_FAILED')):
        app.test_client().get('/api/reposnews/instagram/callback?state=failed&code=fixture')
    assert meta.blocked_view('owner')['status']=='PROVIDER_BLOCKED'
    assert not meta.current('owner').get('resolved_at')
