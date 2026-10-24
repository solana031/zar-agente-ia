"""Focused account/OAuth regression tests. Every provider call is an offline fixture."""
import json
from unittest.mock import Mock, patch
import pytest
from flask import Flask, abort, session, request
from app import holdings, reposnews as rn, reposnews_inbox as inbox, oauth_vault, social_publish
from app.account_connections import AccountConnectionRegistry, Provider, register


@pytest.fixture
def isolated(tmp_path,monkeypatch):
    monkeypatch.setenv('ZAR_DATA_DIR',str(tmp_path))
    monkeypatch.setenv('INSTAGRAM_ACCESS_TOKEN','expired-legacy-fixture')
    monkeypatch.setenv('INSTAGRAM_IG_USER_ID','old-id')
    rn.write({'owner':'owner','articles':[]})
    return rn._path().parent


def identity():
    return Mock(ok=True,json=lambda:{'username':'zaragente031','user_id':'12345'})


def record():
    return {'access_token':'new-oauth-fixture','user_id':'12345','username':'zaragente031','issued_at':'2026-10-21T12:00:00+00:00'}


def test_atomic_persistence_replaces_old_and_readback_uses_new(isolated):
    oauth_vault.persist(isolated/'instagram-oauth',json.dumps(dict(record(),access_token='old-oauth-fixture',issued_at='2026-10-20')),isolated)
    oauth_vault.persist(isolated/'instagram-oauth-pending',json.dumps(record()),isolated)
    with patch.object(inbox.requests,'get',return_value=identity()) as read:
        loaded=inbox.persist_identity(record())
    assert read.call_args.kwargs['headers']['Authorization']=='Bearer new-oauth-fixture'
    assert loaded['access_token']=='new-oauth-fixture'
    assert social_publish.instagram_context('owner')['token']=='new-oauth-fixture'
    assert not (isolated/'instagram-oauth-pending').exists()
    assert 'new-oauth-fixture' not in (isolated/'instagram-oauth').read_text()
    diagnostic=rn.read()['instagram_credential_diagnostic']
    assert diagnostic['NEW_TOKEN_PERSISTED'] and diagnostic['NEW_TOKEN_READBACK']
    assert diagnostic['STALE_SOURCE_SELECTED'] is False
    assert 'new-oauth-fixture' not in json.dumps(diagnostic)


def test_corrupt_canonical_never_resurrects_legacy_env(isolated):
    (isolated/'instagram-oauth').write_text('corrupt')
    assert inbox.credentials()=={}
    assert social_publish.instagram_context('owner')['token']==''


def test_mismatched_persistent_readback_cannot_claim_success(isolated):
    with patch.object(inbox,'credentials',return_value=dict(record(),access_token='unexpected-fixture')):
        with pytest.raises(ValueError,match='PERSISTENT_CREDENTIAL_MISMATCH'):inbox.persist_identity(record())
    proof=rn.read()['instagram_credential_diagnostic']
    assert proof['NEW_TOKEN_PERSISTED'] and not proof['NEW_TOKEN_READBACK'] and proof['STALE_SOURCE_SELECTED']


def test_failed_readback_identity_cannot_claim_connected(isolated):
    with patch.object(inbox.requests,'get',return_value=Mock(ok=False)):
        with pytest.raises(ValueError,match='PERSISTENT_IDENTITY_NOT_VERIFIED'):inbox.persist_identity(record())
    assert not rn.read()['instagram_credential_diagnostic']['NEW_TOKEN_READBACK']
    assert inbox.credentials()['access_token']=='new-oauth-fixture'


def test_older_callback_never_replaces_newer_credential(isolated):
    oauth_vault.persist(isolated/'instagram-oauth',json.dumps(record()),isolated)
    with pytest.raises(ValueError,match='SUPERSEDED'):inbox.persist_identity(dict(record(),issued_at='2026-10-20'))
    assert inbox.credentials()['issued_at']==record()['issued_at']


def test_registry_get_has_no_network_and_no_false_connected(isolated):
    registry=AccountConnectionRegistry('owner')
    with patch.object(inbox.requests,'get') as read:
        data=registry.view()
    read.assert_not_called()
    assert {x['id'] for x in data['providers']}=={'google','youtube','instagram','tiktok','shopify'}
    assert all(x['status']=='UNKNOWN' for x in data['providers'])
    assert data['summary']['connected']==0
    assert 'expired-legacy-fixture' not in json.dumps(data)


def test_tiktok_existing_app_access_is_an_exact_human_action_not_fake_ready(isolated):
    from app.account_connections import social
    data=holdings.read('owner');data['tiktok_setup_observation']={'existing_app_access_required':True,'organization':'ZAR'};holdings.write('owner',data)
    with patch('app.text_video_social._provider_connections',return_value={'tiktok':{'connected':False,'ready':False,'status':'DISCONNECTED'}}):
        result=social('owner','tiktok')
    assert result['status']=='PERMISSION_REQUIRED' and result['ready'] is False
    assert result['blocker']=='TIKTOK_EXISTING_APP_ACCESS_REQUIRED'
    assert 'No crees otra app' in result['human_action']


def test_social_ready_notification_is_deduplicated_in_existing_bell(isolated):
    registry=AccountConnectionRegistry('owner')
    registry.notification('youtube',{'status':'UPLOAD_READY','ready':True})
    registry.notification('youtube',{'status':'UPLOAD_READY','ready':True})
    rows=holdings.read('owner')['identity_center']['human_actions']
    assert len(rows)==1 and rows[0]['type']=='SOCIAL_ACCOUNT_READY' and rows[0]['status']=='DONE'


def test_notifications_deduplicate_and_resolve(isolated):
    registry=AccountConnectionRegistry('owner')
    registry.providers=[Provider('instagram','Instagram','SOCIAL','I',('ReposNews',),lambda scope:{'status':'REAUTH_REQUIRED','human_action':'Reconecta Instagram.'})]
    registry.reverify('instagram');registry.reverify('instagram')
    rows=holdings.read('owner')['identity_center']['human_actions']
    assert len(rows)==1
    assert rows[0]['deep_link']=='/accounts#instagram'
    registry.providers=[Provider('instagram','Instagram','SOCIAL','I',('ReposNews',),lambda scope:{'status':'CONNECTED','account':'zaragente031'})]
    registry.reverify('instagram')
    assert holdings.read('owner')['identity_center']['human_actions'][0]['status']=='DONE'


def test_shopify_uses_only_existing_identity_probe(isolated,monkeypatch):
    monkeypatch.setenv('SHOPIFY_ADMIN_ACCESS_TOKEN','fixture-only')
    monkeypatch.setenv('SHOPIFY_SHOP_DOMAIN','fixture.myshopify.com')
    from app.commerce_adapters import ShopifyAdapter
    with patch.object(ShopifyAdapter,'verify',return_value={'shop':{'id':'gid://Shopify/Shop/1','name':'Fixture','myshopifyDomain':'fixture.myshopify.com'},'currentAppInstallation':{'accessScopes':[{'handle':'read_products'}]}}) as read:
        result=AccountConnectionRegistry('owner').reverify('shopify')
    read.assert_called_once()
    assert result['status']=='CONNECTED' and result['store']=='fixture.myshopify.com'
    assert 'fixture-only' not in json.dumps(result)


def test_account_routes_require_session_and_csrf(isolated):
    app=Flask(__name__,template_folder='../app/templates');app.secret_key='fixture'
    def csrf():
        if session.get('zar_auth') is not True:abort(401)
        if request.headers.get('X-ZAR-Business-CSRF')!=session.get('business_csrf'):abort(403)
        return 'owner'
    register(app,lambda:'owner',csrf);client=app.test_client()
    assert client.get('/api/accounts/connections').status_code==401
    with client.session_transaction() as s:s['zar_auth']=True
    data=client.get('/api/accounts/connections').json
    assert client.post('/api/accounts/connections/instagram/reverify').status_code==403
    headers={'X-ZAR-Business-CSRF':data['csrf']}
    result=client.post('/api/accounts/connections/tiktok/connect',headers=headers).json
    assert result['assistant']=='tiktok' and result['url']=='/accounts#tiktok'
    assert client.post('/api/accounts/connections/instagram/publish',headers=headers).status_code==404
    assert client.post('/api/accounts/connections/no-such-provider/reverify',headers=headers).status_code==404


def test_instagram_identity_and_capabilities_are_independent(isolated):
    from app.account_connections import social
    with patch('app.text_video_social._provider_connections',return_value={'instagram':{'connected':True,'ready':False,'status':'PERMISSION_REQUIRED','capabilities':{'messaging':'READY','reel_discovery':'READY','publishing':'PERMISSION_REQUIRED'}}}):
        result=social('owner','instagram')
    assert result['status']=='PARTIAL' and result['connected'] and not result['ready']
    assert result['capabilities']['messaging']=='READY'


def test_social_facade_preserves_publication_readiness_contract(isolated):
    from app import text_video_social
    evidence={'instagram':{'connected':True,'ready':True,'publish_capability':'AUTHORIZED_NOT_TESTED','account':'zaragente031','status':'CONNECTED'},
              'tiktok':{'connected':True,'ready':True,'status':'CONNECTED','privacy_options':['SELF_ONLY'],'max_video_post_duration_sec':60,'account_id':'zaragente031'}}
    with patch.object(text_video_social,'_provider_connections',side_effect=lambda scope,only:{key:evidence[key] for key in only}):
        result=text_video_social.connections('owner',['instagram','tiktok'])
    assert result['instagram']['publish_capability']=='AUTHORIZED_NOT_TESTED'
    assert result['tiktok']['max_video_post_duration_sec']==60
    assert result['instagram']['connect_url']=='/accounts#instagram'


def test_valid_pending_recovery_uses_only_identity_reads(isolated):
    oauth_vault.persist(isolated/'instagram-oauth-pending',json.dumps(record()),isolated)
    with patch.object(inbox.requests,'get',return_value=identity()) as read,patch.object(inbox.requests,'post') as write:
        assert inbox.recover_pending_identity()
    assert read.call_count==2
    write.assert_not_called()
    assert social_publish.instagram_context('owner')['token']=='new-oauth-fixture'
    assert not (isolated/'instagram-oauth-pending').exists()
