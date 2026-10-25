"""OAuth regression: isolated cookie jars, no live grants or token exchange."""
import ast
import json
import os
from pathlib import Path
import secrets
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit
from flask import Flask, session, request, jsonify, redirect
from app import oauth_transport as transport, account_connections, reposnews_inbox, cloud_auth
from app.user_scope import get_current_user, set_current_user

BASE='https://web-production-a9565.up.railway.app'

class OAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='zar-oauth-test-',dir=Path.cwd());self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ,{'ZAR_DATA_DIR':self.tmp.name,'PUBLIC_BASE_URL':BASE,
            'ZAR_ACCESS_PASSWORD':'TEST-only','INSTAGRAM_APP_ID':'TEST','INSTAGRAM_APP_SECRET':'TEST'},clear=True)
        self.env.start();self.addCleanup(self.env.stop)
        self.app=Flask(__name__);self.app.secret_key='TEST-only'
        self.app.config.update(SERVER_NAME=urlsplit(BASE).netloc,PREFERRED_URL_SCHEME='https',SESSION_COOKIE_SECURE=True,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax')
        self.scope=lambda:session.get('zar_user_id','other')
        def csrf():
            from flask import abort
            if not session.get('zar_auth') or request.headers.get('X-ZAR-Business-CSRF')!='TEST':abort(403)
            return self.scope()
        account_connections.register(self.app,self.scope,csrf)
        reposnews_inbox.register(self.app,self.scope)
        names={'_guard','_auth_enabled','_authorized','oauth2callback','_save_oauth_pending','_load_oauth_pending','_clear_oauth_pending','_canonical_origin','_google_redirect_uri'}
        tree=ast.parse(Path('app/main.py').read_text(encoding='utf-8-sig'))
        self.finish=Mock()
        self.ns=dict(__name__='app.main',__package__='app',app=self.app,os=os,time=time,secrets=secrets,
            session=session,request=request,jsonify=jsonify,redirect=redirect,get_current_user=get_current_user,
            set_current_user=set_current_user,finish_oauth=self.finish,
            _oauth_error_page=lambda message:'OAuth error',_oauth_success_page=lambda provider:'Connected')
        exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),'oauth-test','exec'),self.ns)
        self.owner=self.app.test_client()
        with self.owner.session_transaction() as s:s.update(zar_auth=True,zar_user_id='owner',business_csrf='TEST')

    def test_callbacks_https_and_spoofed_proxy_ignored(self):
        with self.app.test_request_context(headers={'X-Forwarded-Host':'evil.invalid','X-Forwarded-Proto':'http'}):
            self.assertEqual(self.ns['_google_redirect_uri'](),BASE+'/oauth2callback')
            self.assertEqual(transport.callback('instagram'),BASE+'/api/reposnews/instagram/callback')
        with patch.dict(os.environ,{'GOOGLE_REDIRECT_URI':'http://localhost/oauth2callback'}):
            with self.assertRaises(ValueError):transport.callback('google')

    def test_railway_trusts_only_final_proto_not_forwarded_host(self):
        app=Flask('proxy-test')
        with patch.dict(os.environ,{'RAILWAY_ENVIRONMENT_ID':'TEST'}):transport.configure_proxy(app)
        @app.get('/')
        def view():return jsonify(secure=request.is_secure,host=request.host)
        r=app.test_client().get('/',base_url='http://internal.invalid',headers={'X-Forwarded-Proto':'https','X-Forwarded-Host':'evil.invalid'})
        self.assertTrue(r.json['secure']);self.assertEqual(r.json['host'],'internal.invalid')

    def test_store_encrypted_expiring_and_single_use(self):
        transport.put('state:google:TEST',{'verifier':'PRIVATE_TEST_VALUE'})
        self.assertNotIn(b'PRIVATE_TEST_VALUE',Path(self.tmp.name,'oauth_transactions.sqlite3').read_bytes())
        self.assertEqual(transport.get('state:google:TEST',True)['verifier'],'PRIVATE_TEST_VALUE')
        self.assertEqual(transport.get('state:google:TEST',True),{})
        transport.put('expired',{'a':1},ttl=-1)
        self.assertEqual(transport.get('expired'),{})

    def test_google_pkce_and_redirect_generated_without_network(self):
        with patch.object(cloud_auth,'_oauth_client',return_value=('TEST-client','TEST-secret')),patch.object(cloud_auth,'get_credentials',return_value=None):
            url,state,verifier=cloud_auth.authorization_url(force=True,service='core')
        q=parse_qs(urlsplit(url).query)
        self.assertEqual(q['redirect_uri'],[BASE+'/oauth2callback'])
        self.assertEqual(q['state'],[state]);self.assertEqual(q['code_challenge_method'],['S256'])
        self.assertGreaterEqual(len(verifier),43)

    def test_google_callback_without_cookie_and_replay(self):
        transport.put('state:google:TEST-state',dict(state='TEST-state',verifier='TEST-verifier',user_id='owner',redirect_uri=BASE+'/oauth2callback'))
        external=self.app.test_client()
        with patch.object(cloud_auth,'get_credentials',return_value=None):
            response=external.get('/oauth2callback?state=TEST-state&code=TEST-code',base_url=BASE)
        self.assertEqual(response.status_code,200);self.finish.assert_called_once()
        self.assertEqual(external.get('/oauth2callback?state=TEST-state&code=TEST-code',base_url=BASE).status_code,400)

    def test_google_invalid_and_cancelled_state_never_exchange(self):
        self.assertEqual(self.owner.get('/oauth2callback?state=wrong&code=TEST',base_url=BASE).status_code,400)
        transport.put('state:google:cancel',dict(state='cancel',user_id='owner'))
        r=self.app.test_client().get('/oauth2callback?state=cancel&error=access_denied',base_url=BASE)
        self.assertEqual(r.status_code,400);self.assertIn('cancelada',r.text);self.finish.assert_not_called()

    def test_instagram_connect_owner_guard_explains_forbidden(self):
        with patch.object(reposnews_inbox.rn,'state',side_effect=ValueError('owner mismatch')):
            r=self.owner.get('/api/reposnews/instagram/connect',base_url=BASE)
        self.assertEqual(r.status_code,403);self.assertIn('propietaria',r.text);self.assertNotIn('Forbidden',r.text)

    def test_instagram_callback_no_session_invalid_and_wrong_owner(self):
        external=self.app.test_client()
        r=external.get('/api/reposnews/instagram/callback?state=wrong&code=TEST',base_url=BASE)
        self.assertEqual(r.status_code,400);self.assertNotIn('Forbidden',r.text)
        transport.put('state:instagram:TEST',dict(user_id='other',expires=time.time()+60))
        with patch.object(reposnews_inbox.rn,'read',return_value={'owner':'owner'}):
            r=external.get('/api/reposnews/instagram/callback?state=TEST&code=TEST',base_url=BASE)
        self.assertEqual(r.status_code,403)

    def test_instagram_cookie_independent_callback_uses_original_redirect(self):
        pending=dict(value='TEST-state',user_id='owner',expires=time.time()+60,permissions=[],handoff='handoff',redirect_uri=BASE+'/api/reposnews/instagram/callback')
        transport.put('state:instagram:TEST-state',pending)
        with patch.object(reposnews_inbox.rn,'read',return_value={'owner':'owner'}),patch.object(reposnews_inbox.rn,'write'),patch.object(reposnews_inbox.holdings,'transaction'),patch.object(reposnews_inbox.requests,'post',return_value=Mock(ok=False,status_code=400,json=lambda:{})) as post:
            r=self.app.test_client().get('/api/reposnews/instagram/callback?state=TEST-state&code=TEST-code',base_url=BASE)
        self.assertEqual(r.status_code,400)
        self.assertEqual(post.call_args.kwargs['data']['redirect_uri'],pending['redirect_uri'])
        self.assertNotIn('Forbidden',r.text)

    def test_handoff_single_use_csrf_and_no_zar_login_grant(self):
        ident=transport.begin('owner','google','/connect/google?force=1')
        external=self.app.test_client();r=external.get('/oauth/accounts/start/'+ident,base_url=BASE)
        self.assertEqual(r.status_code,302)
        with external.session_transaction() as s:self.assertFalse(s.get('zar_auth'));self.assertEqual(s['zar_user_id'],'owner')
        self.assertEqual(external.get('/oauth/accounts/start/'+ident,base_url=BASE).status_code,400)
        self.assertEqual(external.get('/api/accounts/oauth/status/'+ident,base_url=BASE).status_code,401)
        self.assertEqual(self.owner.post('/api/accounts/connections/google/connect',json={'external':True},base_url=BASE).status_code,403)

    def test_authenticated_external_prepare_and_instagram_success_without_cookie(self):
        with patch.object(account_connections.AccountConnectionRegistry,'connect_url',return_value='/connect/google?force=1'):
            r=self.owner.post('/api/accounts/connections/google/connect',json={'external':True},headers={'X-ZAR-Business-CSRF':'TEST'},base_url=BASE)
        self.assertEqual(r.status_code,200)
        self.assertTrue(r.json['url'].startswith(BASE+'/oauth/accounts/start/'))
        ident=transport.begin('owner','instagram','/api/reposnews/instagram/connect')
        transport.put('state:instagram:success',dict(value='success',user_id='owner',expires=time.time()+60,permissions=[],handoff=ident,redirect_uri=transport.callback('instagram')))
        token_response=Mock(ok=True,json=lambda:{'access_token':'TEST-only-token','user_id':'123'})
        identity_response=Mock(ok=True,json=lambda:{'username':'zaragente031','user_id':'123'})
        def get(url,**kwargs):
            if url=='https://graph.instagram.com/access_token':return Mock(ok=True,json=lambda:{'access_token':'TEST-only-long-token','expires_in':5184000})
            return identity_response
        with patch.object(reposnews_inbox.rn,'read',return_value={'owner':'owner'}),patch.object(reposnews_inbox.rn,'write'),patch.object(reposnews_inbox.holdings,'transaction'),patch.object(reposnews_inbox.requests,'post',return_value=token_response),patch.object(reposnews_inbox.requests,'get',side_effect=get),patch.object(reposnews_inbox,'persist_identity',side_effect=lambda record:record),patch.object(reposnews_inbox,'verify_capabilities',return_value={'manage_messages':'PERMISSION_REQUIRED'}):
            r=self.app.test_client().get('/api/reposnews/instagram/callback?state=success&code=TEST',base_url=BASE)
        self.assertEqual(r.status_code,200);self.assertIn('completada',r.text)
        self.assertNotIn('TEST-only-token',r.text)
        self.assertEqual(transport.get('result:'+ident)['status'],'CONNECTED')

    def test_poll_bound_to_original_owner_and_migrates_only_after_success(self):
        ident=transport.begin('owner','google','/connect/google')
        transport.complete(ident,'CONNECTED','new-google-scope')
        with self.owner.session_transaction() as s:s['zar_user_id']='other'
        self.assertEqual(self.owner.get('/api/accounts/oauth/status/'+ident,base_url=BASE).status_code,404)
        with self.owner.session_transaction() as s:s['zar_user_id']='owner'
        r=self.owner.get('/api/accounts/oauth/status/'+ident,base_url=BASE)
        self.assertEqual(r.json['status'],'CONNECTED')
        with self.owner.session_transaction() as s:self.assertEqual(s['zar_user_id'],'new-google-scope')
        self.assertEqual(self.owner.get('/api/accounts/oauth/status/'+ident,base_url=BASE).status_code,404)

    def test_same_browser_popup_preserves_existing_login_and_migration_receipt(self):
        r=self.owner.post('/api/accounts/connections/google/reconnect',json={'external':True},headers={'X-ZAR-Business-CSRF':'TEST'},base_url=BASE)
        ident=r.json['poll_id']
        self.assertEqual(self.owner.get('/oauth/accounts/start/'+ident,base_url=BASE).status_code,302)
        with self.owner.session_transaction() as s:self.assertTrue(s['zar_auth'])
        transport.complete(ident,'CONNECTED','migrated-owner')
        with self.owner.session_transaction() as s:s['zar_user_id']='migrated-owner'
        self.assertEqual(self.owner.get('/api/accounts/oauth/status/'+ident,base_url=BASE).json['status'],'CONNECTED')
        # A separate authenticated cookie for the destination scope has no
        # initiating receipt and cannot adopt or consume this transaction.
        ident=transport.begin('original-owner','google','/connect/google')
        transport.complete(ident,'CONNECTED','migrated-owner')
        other=self.app.test_client()
        with other.session_transaction() as s:s.update(zar_auth=True,zar_user_id='migrated-owner')
        self.assertEqual(other.get('/api/accounts/oauth/status/'+ident,base_url=BASE).status_code,404)
        self.assertTrue(transport.get('result:'+ident))

    def test_youtube_uses_same_external_handoff_and_iframe_cannot_consume_it(self):
        r=self.owner.post('/api/accounts/connections/youtube/reconnect',json={'external':True},headers={'X-ZAR-Business-CSRF':'TEST'},base_url=BASE)
        self.assertTrue(r.json['external']);ident=r.json['poll_id']
        blocked=self.owner.get('/oauth/accounts/start/'+ident,base_url=BASE,headers={'Sec-Fetch-Dest':'iframe'})
        self.assertEqual(blocked.status_code,200);self.assertIn('ventana externa',blocked.text)
        self.assertIn('target="_blank"',blocked.text)
        self.assertTrue(transport.get('launch:'+ident))
        self.assertEqual(self.owner.get('/oauth/accounts/start/'+ident,base_url=BASE,headers={'Sec-Fetch-Dest':'document'}).status_code,302)

    def test_external_deep_link_preserves_expected_email_and_service(self):
        path='/connect/google?purpose=zar&service=docs&email=zaragente031%40gmail.com&force=1'
        response=self.owner.post('/api/accounts/connections/google/reconnect',json={'external':True,'authorization_path':path},headers={'X-ZAR-Business-CSRF':'TEST'},base_url=BASE)
        self.assertEqual(transport.get('launch:'+response.json['poll_id'])['path'],path)
        for path in ['https://evil.test/connect/google','//evil.test/connect/google','/connect/google?service=youtube','/oauth2callback']:
            self.assertEqual(self.owner.post('/api/accounts/connections/google/reconnect',json={'external':True,'authorization_path':path},headers={'X-ZAR-Business-CSRF':'TEST'},base_url=BASE).status_code,400)

    def test_provider_routes_explain_iframe_instead_of_redirecting_to_provider(self):
        for path in ['/connect/google','/connect/youtube','/api/reposnews/instagram/connect']:
            response=self.owner.get(path,base_url=BASE,headers={'Sec-Fetch-Dest':'iframe'})
            self.assertEqual(response.status_code,200)
            self.assertNotIn('Location',response.headers)
            self.assertIn('/static/oauth-launcher.js',response.text)
        with self.app.test_request_context():
            response=transport.page('Instagram','CONNECTED',200)
            self.assertIn('Cuenta conectada correctamente.',response.get_data(as_text=True))
            self.assertIn('data-oauth-provider="instagram"',response.get_data(as_text=True))
            self.assertIn('/static/oauth-callback.js',response.get_data(as_text=True))

    def test_cookie_and_safe_error(self):
        ident=transport.begin('owner','google','/connect/google')
        r=self.app.test_client().get('/oauth/accounts/start/'+ident,base_url=BASE)
        cookie=r.headers['Set-Cookie']
        for flag in ('Secure','HttpOnly','SameSite=Lax','Path=/'):self.assertIn(flag,cookie)
        self.assertNotIn('Domain=',cookie)
        with self.app.test_request_context():
            r=transport.page('Instagram','OAUTH_STATE_INVALID')
            self.assertEqual(r.headers['Referrer-Policy'],'no-referrer')

if __name__=='__main__':unittest.main()
