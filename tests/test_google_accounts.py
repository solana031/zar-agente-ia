"""Native Google account grants are mocked; encryption and callbacks are real."""
import ast
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit
from datetime import datetime,timedelta,timezone
from google.oauth2.credentials import Credentials
from tests import test_oauth_transport as fixture
from app import google_accounts as accounts,cloud_auth,oauth_vault,oauth_transport,holdings,account_connections

BASE=fixture.BASE

def credential(token):
    return Credentials(token=token,refresh_token='TEST-refresh-'+token,token_uri='https://oauth2.googleapis.com/token',
        client_id='TEST-client',client_secret='TEST-secret',scopes=cloud_auth.CORE_SCOPES,expiry=datetime.now(timezone.utc)+timedelta(hours=1))

class GoogleAccountTests(unittest.TestCase):
    setUp=fixture.OAuthTests.setUp

    def test_free_selector_has_no_admin_hint_or_account_restriction(self):
        url=account_connections.AccountConnectionRegistry('owner').connect_url('google')
        q=parse_qs(urlsplit(url).query)
        self.assertEqual(q['purpose'],['accounts']);self.assertNotIn('email',q)
        with patch.object(cloud_auth,'_oauth_client',return_value=('TEST-client','TEST-secret')),patch.object(cloud_auth,'get_credentials',return_value=None):
            url,_,_=cloud_auth.authorization_url(force=True,service='core')
        q=parse_qs(urlsplit(url).query)
        self.assertIn('select_account',q['prompt'][0]);self.assertNotIn('login_hint',q);self.assertNotIn('hd',q)

    def test_legacy_module_links_use_free_selection_but_operational_hints_remain(self):
        for path in ('/connect/google?force=1','/connect/google?force=1&purpose=zar&email=zaragente031%40gmail.com&service=core'):
            r=self.owner.post('/api/accounts/connections/google/connect',json={'external':True,'authorization_path':path},headers={'X-ZAR-Business-CSRF':'TEST'},base_url=BASE)
            self.assertEqual(r.status_code,200)
            saved=oauth_transport.get('launch:'+r.json['poll_id'])
            self.assertIn('purpose=zar' if 'purpose=zar' in path else 'purpose=accounts',saved['path'])

    def test_selection_requires_csrf_and_cannot_adopt_another_owners_account(self):
        key=accounts.attach('other',credential('TEST-other'),'solana031@gmail.com')
        self.assertEqual(self.owner.post('/api/accounts/google/select',json={'account_id':key},base_url=BASE).status_code,403)
        self.assertEqual(self.owner.post('/api/accounts/google/select',json={'account_id':key},headers={'X-ZAR-Business-CSRF':'TEST'},base_url=BASE).status_code,400)

    def test_two_accounts_survive_selection_reload_and_other_scope_cannot_select(self):
        first=accounts.attach('owner',credential('TEST-zar'),'zaragente031@gmail.com')
        second=accounts.attach('owner',credential('TEST-personal'),'solana031@gmail.com')
        self.assertEqual({r['email'] for r in accounts.view('owner')},{'solana031@gmail.com','zaragente031@gmail.com'})
        with patch.object(cloud_auth,'DATA_DIR',Path(self.tmp.name)):
            self.assertEqual(cloud_auth.get_credentials(auto_refresh=False,user_id='owner').token,'TEST-personal')
            accounts.select('owner',first)
            self.assertEqual(cloud_auth.get_credentials(auto_refresh=False,user_id='owner').token,'TEST-zar')
            # A refresh already in progress must write its original file even if selection changes.
            path=cloud_auth._token_file('owner');accounts.select('owner',second)
            cloud_auth._save_credentials(credential('TEST-refreshed-zar'),user_id='owner',path=path)
            self.assertEqual(cloud_auth.get_credentials(auto_refresh=False,user_id='owner').token,'TEST-personal')
        with self.assertRaises(ValueError):accounts.select('other',first)
        data=Path(self.tmp.name,'users','owner','google_accounts.json').read_text()
        self.assertNotIn('solana031@gmail.com',data);self.assertNotIn('TEST-personal',data)

    def test_legacy_token_and_reauthorization_history_are_preserved(self):
        legacy=accounts.root('owner')/'google_token.json'
        oauth_vault.persist(legacy,credential('TEST-old-zar').to_json(),self.tmp.name)
        original=legacy.read_bytes()
        holdings.write('owner',{'identity_center':{'google':{'email':'zaragente031@gmail.com'}}})
        key=accounts.attach('owner',credential('TEST-personal'),'solana031@gmail.com')
        self.assertEqual(legacy.read_bytes(),original)
        self.assertIn('legacy',accounts.read('owner')['accounts'])
        accounts.attach('owner',credential('TEST-renewed'),'solana031@gmail.com')
        history=list((accounts.root('owner')/'google_accounts'/'history').glob('*.json'))
        self.assertEqual(len(history),1)
        old=oauth_vault.decode(history[0].read_text(),self.tmp.name)
        self.assertEqual(old['token'],'TEST-personal');self.assertEqual(legacy.read_bytes(),original)

    def test_personal_callback_keeps_zar_owner_and_does_not_grant_external_login(self):
        ident=oauth_transport.begin('owner','google','/connect/google?force=1&purpose=accounts&service=core')
        oauth_transport.put('state:google:TEST-free',dict(state='TEST-free',verifier='TEST-pkce',user_id='owner',
            purpose='accounts',service='core',handoff=ident,redirect_uri=BASE+'/oauth2callback'))
        # Run the actual success renderer to complete the server receipt.
        tree=ast.parse(Path('app/main.py').read_text(encoding='utf-8-sig'))
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_oauth_success_page')
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'success','exec'),self.ns)
        self.finish.return_value=credential('TEST-personal')
        external=self.app.test_client()
        with patch.object(cloud_auth,'get_account_email',return_value='solana031@gmail.com'):
            response=external.get('/oauth2callback?state=TEST-free&code=TEST-code',base_url=BASE)
        self.assertEqual(response.status_code,200)
        self.assertFalse(self.finish.call_args.kwargs['persist'])
        with external.session_transaction() as s:
            self.assertEqual(s['zar_user_id'],'owner');self.assertFalse(s.get('zar_auth'))
        self.assertEqual(oauth_transport.get('result:'+ident)['result_scope'],'owner')
        self.assertNotIn('data-oauth-return="1"',response.text)
        self.assertEqual(accounts.view('owner')[0]['email'],'solana031@gmail.com')
        self.assertEqual(external.get('/oauth2callback?state=TEST-free&code=TEST-code',base_url=BASE).status_code,400)

    def test_existing_authenticated_session_returns_automatically_and_persists_bounded_cookie(self):
        r=self.owner.post('/api/accounts/connections/google/connect',json={'external':True},headers={'X-ZAR-Business-CSRF':'TEST'},base_url=BASE)
        self.assertEqual(r.status_code,200)
        cookie=r.headers['Set-Cookie']
        for value in ('Expires=','Secure','HttpOnly','SameSite=Lax'):self.assertIn(value,cookie)
        self.assertEqual(self.app.permanent_session_lifetime,timedelta(days=7))
        with self.app.test_request_context():
            from flask import session
            session['zar_auth']=True
            response=oauth_transport.page('Google','CONNECTED',200)
            self.assertIn('data-oauth-return="1"',response.get_data(as_text=True))

    def test_personal_verification_does_not_enforce_operational_identity_or_reuse_its_proofs(self):
        accounts.attach('owner',credential('TEST-personal'),'solana031@gmail.com')
        with patch.object(cloud_auth,'get_credentials',return_value=credential('TEST-personal')),patch.object(cloud_auth,'get_account_email',return_value='solana031@gmail.com'),patch.object(account_connections.identity_center,'_probe',return_value={'status':'CONNECTED'}),patch.object(account_connections.identity_center,'verify_google') as operational:
            result=account_connections.google('owner')
        self.assertEqual(result['account'],'solana031@gmail.com');self.assertTrue(result['connected'])
        self.assertNotEqual(result['capabilities']['FORMS'],'READY');operational.assert_not_called()
