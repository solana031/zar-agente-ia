"""OAuth, renewal and isolation; every TikTok request is mocked."""
import json
import time
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock, patch

import pytest
from flask import Flask, abort, request, session
from app import account_connections, oauth_transport as transport, oauth_vault, tiktok_oauth as tt

BASE='https://zar.example'


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('ZAR_DATA_DIR',str(tmp_path))
    monkeypatch.setenv('PUBLIC_BASE_URL',BASE)
    monkeypatch.setenv('TIKTOK_CLIENT_KEY','fixture-key')
    monkeypatch.setenv('TIKTOK_CLIENT_SECRET','fixture-secret')
    monkeypatch.delenv('TIKTOK_REDIRECT_URI',raising=False)
    app=Flask(__name__);app.secret_key='test-only'
    def csrf():
        if not session.get('zar_auth'):abort(401)
        if request.headers.get('X-ZAR-Business-CSRF')!='fixture':abort(403)
        return session['zar_user_id']
    account_connections.register(app,lambda:session.get('zar_user_id','anonymous'),csrf)
    return app.test_client()


def token(**changes):
    return dict(access_token='private-access-fixture',refresh_token='private-refresh-fixture',open_id='id-1',
        expires_in=7200,refresh_expires_in=86400,scope='video.publish,user.info.basic',**changes)


def login(client):
    with client.session_transaction() as s:s.update(zar_auth=True,zar_user_id='owner')


def test_prepare_requires_session_csrf_and_configuration(client,monkeypatch):
    url='/api/accounts/connections/tiktok/reconnect'
    assert client.post(url,json={'external':True}).status_code==401
    login(client)
    assert client.post(url,json={'external':True}).status_code==403
    monkeypatch.delenv('TIKTOK_CLIENT_SECRET')
    r=client.post(url,json={'external':True},headers={'X-ZAR-Business-CSRF':'fixture'})
    assert r.status_code==409 and r.json['error']=='TIKTOK_SETUP_REQUIRED'
    assert 'fixture-secret' not in r.text


def test_handoff_stays_on_current_origin_and_callback_without_cookie(client):
    login(client)
    r=client.post('/api/accounts/connections/tiktok/reconnect',json={'external':True},headers={'X-ZAR-Business-CSRF':'fixture'})
    ident=r.json['poll_id']
    assert r.json['url']=='/oauth/accounts/start/'+ident
    external=client.application.test_client()
    assert external.get(r.json['url']).status_code==302
    redirect=external.get('/connect/tiktok')
    query=parse_qs(urlsplit(redirect.location).query)
    assert query['redirect_uri']==[BASE+'/oauth/tiktok/callback']
    assert query['scope']==['user.info.basic,video.publish']
    assert 'fixture-secret' not in redirect.location
    callback=client.application.test_client()
    with patch.object(tt.requests,'post',return_value=Mock(ok=True,json=lambda:token())) as post:
        response=callback.get('/oauth/tiktok/callback',query_string={'state':query['state'][0],'code':'fixture-code'})
        assert response.status_code==200
        assert post.call_args.kwargs['data']['redirect_uri']==BASE+'/oauth/tiktok/callback'
        assert callback.get('/oauth/tiktok/callback',query_string={'state':query['state'][0],'code':'fixture-code'}).status_code==400
        assert post.call_count==1
    assert 'private-access-fixture' not in response.text
    assert tt.access_token('owner')=='private-access-fixture'
    path,_=tt._path('owner')
    assert 'private-access-fixture' not in path.read_text()
    with callback.session_transaction() as s:assert not s.get('zar_auth')
    assert client.get('/api/accounts/oauth/status/'+ident).json['status']=='CONNECTED'
    assert tt._path('someone-else')[0].exists() is False


@pytest.mark.parametrize('cancelled',[True,False])
def test_cancel_or_failed_exchange_preserves_previous_authorization(client,cancelled):
    path,root=tt._path('owner')
    oauth_vault.persist(path,json.dumps(dict(token(),expires_at=time.time()+4000)),root)
    transport.put('state:tiktok:fixture',{'scope':'owner','callback':BASE+'/oauth/tiktok/callback'})
    with patch.object(tt.requests,'post',return_value=Mock(ok=False,json=lambda:{'error':'invalid_grant'})) as post:
        args={'state':'fixture',**({'error':'access_denied'} if cancelled else {'code':'fixture'})}
        assert client.get('/oauth/tiktok/callback',query_string=args).status_code==400
        assert post.call_count==(0 if cancelled else 1)
    assert tt.access_token('owner')=='private-access-fixture'


def test_renewal_persists_rotated_refresh_token_and_is_scoped(client,monkeypatch):
    monkeypatch.setenv('TIKTOK_ACCESS_TOKEN','legacy-fixture')
    path,root=tt._path('owner')
    original=dict(token(),expires_at=time.time()-1,refresh_expires_at=time.time()+9000)
    oauth_vault.persist(path,json.dumps(original),root)
    renewed=token();renewed.update(access_token='new-private-access',refresh_token='new-private-refresh')
    with patch.object(tt.requests,'post',return_value=Mock(ok=True,json=lambda:renewed)) as post:
        assert tt.access_token('owner')=='new-private-access'
        assert tt.access_token('owner')=='new-private-access'
        assert post.call_count==1
        assert post.call_args.kwargs['data']['refresh_token']=='private-refresh-fixture'
    assert oauth_vault.decode(path.read_text(),root)['refresh_token']=='new-private-refresh'
    assert tt.access_token('other')=='legacy-fixture'
    path.write_text('broken')
    with pytest.raises(ValueError):tt.access_token('owner')


def test_untrusted_or_expired_state_cannot_exchange(client):
    transport.put('state:tiktok:expired',{'scope':'owner'},ttl=-1)
    with patch.object(tt.requests,'post') as post:
        for state in ('missing','expired'):
            assert client.get('/oauth/tiktok/callback',query_string={'state':state,'code':'fixture'}).status_code==400
        post.assert_not_called()
    assert client.get('/connect/tiktok').status_code==401


def test_misconfigured_callback_is_actionable(client,monkeypatch):
    login(client);monkeypatch.setenv('TIKTOK_REDIRECT_URI','https://wrong.example/oauth/tiktok/callback')
    r=client.post('/api/accounts/connections/tiktok/reconnect',json={'external':True},headers={'X-ZAR-Business-CSRF':'fixture'})
    assert r.status_code==409 and r.json['error']=='OAUTH_CONFIGURATION_REQUIRED'
