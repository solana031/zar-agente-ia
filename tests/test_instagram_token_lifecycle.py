"""Official token lifecycle, entirely offline; credentials below are test fixtures."""
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch
import pytest
from app import instagram_tokens as t, reposnews as rn, oauth_vault, holdings


@pytest.fixture
def store(tmp_path,monkeypatch):
    monkeypatch.setenv('ZAR_DATA_DIR',str(tmp_path))
    monkeypatch.setenv('INSTAGRAM_APP_SECRET','fixture-app-secret')
    rn.write({'owner':'owner','articles':[]})
    return rn._path().parent


def record(**overrides):
    now=time.time()
    return dict({'access_token':'long-fixture','user_id':'123','username':'zaragente031',
        'issued_at':t.stamp(now-2*t.DAY),'authorization_started_at':t.stamp(now-2*t.DAY),
        'identity_verified_at':t.stamp(now-2*t.DAY),'expires_at':t.stamp(now+2*t.DAY),
        'renew_after':t.stamp(now-1),'refresh_not_before':t.stamp(now-t.DAY),
        'token_class':'LONG_LIVED','acquired_by':'IG_EXCHANGE_TOKEN'},**overrides)


def save(value):
    oauth_vault.persist(t.path(),json.dumps(value),rn._path().parent)


def response(body,http=200):return Mock(ok=http<400,status_code=http,json=lambda:body)
def identity():return response({'username':'zaragente031','user_id':'123'})


@pytest.mark.parametrize('wrapped',[True,False])
def test_exchange_official_endpoint_and_real_lifetime(store,wrapped):
    short={'access_token':'short-fixture','permissions':'instagram_business_basic,instagram_business_manage_messages'}
    with patch.object(t.requests,'get',return_value=response({'access_token':'long-fixture','token_type':'bearer','expires_in':5184000})) as call:
        result=t.exchange_short({'data':[short]} if wrapped else short)
    assert call.call_args.args==('https://graph.instagram.com/access_token',)
    assert call.call_args.kwargs['params']=={'grant_type':'ig_exchange_token','client_secret':'fixture-app-secret','access_token':'short-fixture'}
    assert call.call_args.kwargs['allow_redirects'] is False
    assert result['token_class']=='LONG_LIVED' and result['renewable']
    assert abs(t.epoch(result['expires_at'])-t.epoch(result['issued_at'])-5184000)<.01
    assert t.epoch(result['renew_after'])==pytest.approx(t.epoch(result['expires_at'])-7*t.DAY)
    assert not t.path().exists()  # Exchange alone cannot promote an unverified identity.


def test_missing_lifetime_or_failed_exchange_never_replaces_good_token(store):
    save(record());before=t.path().read_bytes()
    for body,http in [({'access_token':'unverified-fixture'},200),({'error':{'code':190,'message':'expired short-fixture fixture-app-secret'}},401)]:
        with patch.object(t.requests,'get',return_value=response(body,http)),pytest.raises(t.TokenError) as error:
            t.exchange_short({'access_token':'short-fixture'})
        assert 'short-fixture' not in str(error.value.detail) and 'fixture-app-secret' not in str(error.value.detail)
        assert t.path().read_bytes()==before
    with pytest.raises(t.TokenError,match='LONG_LIVED_EXCHANGE_REQUIRED'):t.promote({'access_token':'short-fixture'})


def test_proactive_refresh_once_and_restart_keeps_daily_guard(store):
    save(record())
    def get(url,**kwargs):
        if url.endswith('/refresh_access_token'):
            assert kwargs['params']=={'grant_type':'ig_refresh_token','access_token':'long-fixture'}
            return response({'access_token':'refreshed-fixture','expires_in':5184000,'token_type':'bearer'})
        assert kwargs['headers']['Authorization']=='Bearer refreshed-fixture'
        return identity()
    with patch.object(t.requests,'get',side_effect=get) as calls:
        t.tick('owner');t.tick('owner')
    assert calls.call_count==3  # One refresh, identity before write, identity from readback.
    assert t.canonical()['access_token']=='refreshed-fixture'
    check="from app import instagram_tokens as t;from unittest.mock import patch\nwith patch.object(t.requests,'get',side_effect=AssertionError('unexpected network')):t.tick('owner')\nassert t.canonical()['access_token']=='refreshed-fixture'\nprint('PERSISTENCE_OK')"
    child=subprocess.run([sys.executable,'-c',check],capture_output=True,text=True,env=os.environ.copy(),timeout=20)
    assert child.returncode==0,child.stderr
    assert child.stdout.strip().splitlines()[-1]=='PERSISTENCE_OK'
    assert 'refreshed-fixture' not in t.path().read_text()
    assert 'refreshed-fixture' not in json.dumps(rn.read())


@pytest.mark.parametrize('change',[{'renew_after':t.stamp(time.time()+t.DAY)}, {'refresh_not_before':t.stamp(time.time()+t.DAY)}])
def test_no_refresh_outside_window_or_before_24_hours(store,change):
    save(record(**change))
    with patch.object(t.requests,'get') as call:t.tick('owner');t.tick('owner')
    call.assert_not_called()


def test_expired_short_requires_reauth_without_any_provider_calls(store):
    save(record(token_class='SHORT_LIVED',expires_at=t.stamp(time.time()-1)))
    with patch.object(t.requests,'get') as call:t.tick('owner');t.tick('owner')
    call.assert_not_called()
    assert t._state()['status']=='REAUTH_REQUIRED'
    assert holdings.read('owner')['account_connections']['instagram']['ready'] is False


def test_valid_short_is_upgraded_without_new_oauth(store):
    save(record(token_class='SHORT_LIVED'))
    def get(url,**kwargs):
        if url.endswith('/access_token'):return response({'access_token':'upgraded-fixture','expires_in':5184000})
        return identity()
    with patch.object(t.requests,'get',side_effect=get),patch.object(t.requests,'post') as post:t.tick('owner')
    post.assert_not_called()
    assert t.canonical()['token_class']=='LONG_LIVED' and t.canonical()['access_token']=='upgraded-fixture'


def test_transient_refresh_keeps_credential_and_does_not_request_oauth(store):
    save(record());before=t.path().read_bytes()
    with patch.object(t.requests,'get',return_value=response({'error':{'code':4,'message':'Rate limit'}},429)) as call:
        t.tick('owner');t.tick('owner')
    assert call.call_count==1 and t.path().read_bytes()==before
    assert t._state()['status']=='TOKEN_EXPIRING_SOON'
    assert not holdings.read('owner').get('account_connections',{}).get('instagram',{}).get('human_action')


def test_stale_refresh_and_old_callback_cannot_overwrite_newer_oauth(store):
    new=record(access_token='newer-fixture',authorization_started_at=t.stamp())
    save(new);before=t.path().read_bytes()
    with patch.object(t.requests,'get',return_value=identity()):
        with pytest.raises(t.TokenError,match='SUPERSEDED'):t.promote(record(),expected_token='older-fixture')
        with pytest.raises(t.TokenError,match='SUPERSEDED'):t.promote(record())
    t.confirm_capabilities(['instagram_business_content_publish'],'older-fixture')
    assert t.path().read_bytes()==before


def test_concurrent_workers_make_only_one_refresh_attempt(store):
    save(record())
    with patch.object(t.requests,'get',return_value=response({'error':{'code':4}},429)) as call:
        with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(t.tick,['owner']*4))
    assert call.call_count==1
    assert t.canonical()['access_token']=='long-fixture'


def test_metadata_forensics_uses_provider_expiry_and_preserves_prior_diagnostic(store):
    original=record();original.pop('token_class');original.pop('expires_at')
    save(original)
    data=rn.read();data.update(instagram_credential_diagnostic={'old':True},instagram_conversation_sync={
        'started_at':t.stamp(time.time()+1),'provider_error':{'code':190,'subcode':0,
        'message':'Session has expired on Sunday, 25-Oct-26 09:00:00 PDT.'}});rn.write(data)
    # A provider expiry older than issuance must never be attached to a new credential.
    adopted=t.adopt_legacy()
    assert adopted['token_class']=='SHORT_LIVED' and not adopted['renewable']
    assert t.reported_expiry(data['instagram_conversation_sync']['provider_error'])=='2026-10-25T16:00:00+00:00'
    assert rn.read()['instagram_credential_diagnostic']=={'old':True}
    assert 'long-fixture' not in json.dumps(rn.read())


@pytest.mark.parametrize('sub,cause',[(463,'EXPIRED_TOKEN'),(467,'INVALID_TOKEN'),(458,'AUTHORIZATION_REMOVED'),(460,'PASSWORD_CHANGED')])
def test_provider_causes(sub,cause):assert t.classify({'code':190,'subcode':sub})==cause


def test_expired_message_with_zero_subcode_and_unknown_expiry():
    assert t.classify({'code':190,'subcode':0,'message':'Session has expired'})=='EXPIRED_TOKEN'
    assert t.reported_expiry({'message':'unknown'}) is None
    assert t.state_for({'access_token':'fixture'})=='CONNECTED'  # No fabricated expiry.


def test_recovery_resume_preserves_cursor_and_backoff(store):
    sync={'last_successful_cursor':'fixture-cursor','last_message_id':'42','retry_after':time.time()+600,'checkpoints':{'1':{'cursor':'kept'}}}
    data=rn.read();data['instagram_conversation_sync']=dict(sync);rn.write(data)
    t.resume_after_recovery('owner')
    assert rn.read()['instagram_conversation_sync']==dict(sync,requested=True)


def test_atomic_write_failure_preserves_previous_ciphertext(store):
    save(record());before=t.path().read_bytes()
    with patch.object(oauth_vault,'encode',side_effect=OSError('fixture failure')),pytest.raises(OSError):save(record(access_token='replacement-fixture'))
    assert t.path().read_bytes()==before
    assert not list(store.glob('instagram-oauth.*.tmp'))


def test_multiple_processes_share_vault_key_and_keep_newest_callback(store):
    base=time.time()
    code="""import sys,json
from unittest.mock import Mock,patch
from app import instagram_tokens as t
n=int(sys.argv[1]);base=float(sys.argv[2])
record={'access_token':'process-fixture-'+str(n),'user_id':'123','username':'zaragente031',
 'issued_at':t.stamp(base+n),'authorization_started_at':t.stamp(base+n),
 'token_class':'LONG_LIVED','acquired_by':'IG_EXCHANGE_TOKEN',
 'expires_at':t.stamp(base+5184000),'renew_after':t.stamp(base+4500000)}
with patch.object(t.requests,'get',return_value=Mock(ok=True,json=lambda:{'username':'zaragente031','user_id':'123'})):
 try:t.promote(record)
 except t.TokenError as e:
  if 'SUPERSEDED' not in str(e):raise
print('WORKER_OK')
"""
    children=[subprocess.Popen([sys.executable,'-c',code,str(n),str(base)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=os.environ.copy()) for n in range(4)]
    for child in children:
        out,err=child.communicate(timeout=25)
        assert child.returncode==0,err
        assert out.strip().splitlines()[-1]=='WORKER_OK'
    assert t.canonical()['access_token']=='process-fixture-3'
    assert 'process-fixture' not in t.path().read_text()
    assert 'process-fixture' not in json.dumps(rn.read())


def test_history_known_expired_token_never_spends_quota(store):
    from app import instagram_conversation_history as history
    save(record(expires_at=t.stamp(time.time()-1)))
    data=rn.read();data['instagram_conversation_sync']={'requested':True,'checkpoints':{'c':{'pagination_cursor':'keep'}}};rn.write(data)
    with patch.object(history.requests,'get') as call:
        result=history.sync('owner')
    call.assert_not_called()
    assert result['status']=='AUTH_REQUIRED'
    assert rn.read()['instagram_conversation_sync']['checkpoints']=={'c':{'pagination_cursor':'keep'}}


def test_only_five_selected_ambiguities_are_reprocessed(store):
    from app import reposnews_ambiguity as ambiguity
    ids=[f'{n:024x}' for n in range(19)]
    data=rn.read();data['instagram_inbox']=[{'id':i,'status':'NEEDS_DISAMBIGUATION'} for i in ids]
    selected=ids[:5]
    data['ambiguous_reprocessing']={'round':ambiguity.ROUND,'ids':selected,'completed':[],'identified':[],'enabled':True}
    rn.write(data)
    with patch.object(ambiguity,'identify',return_value={'status':'NEEDS_DISAMBIGUATION','candidates':[],'frames_examined':8}) as identify:
        for _ in range(6):ambiguity.tick()
    assert [c.args[1]['id'] for c in identify.call_args_list]==selected
    assert all('expanded_identification' not in r for r in rn.read()['instagram_inbox'][5:])
