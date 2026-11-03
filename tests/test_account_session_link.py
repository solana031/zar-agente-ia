"""Account recovery requires explicit device proof; no live OAuth or token copies."""
import hashlib
from pathlib import Path
import time
import unittest
from unittest.mock import patch
from tests import test_oauth_transport as fixture
BASE=fixture.BASE
from app import account_connections as accounts, oauth_transport as transport


class DeviceSessionTests(unittest.TestCase):
    setUp=fixture.OAuthTests.setUp
    # Reuse the isolated Flask harness, not production main/background workers.
    def pair_request(self,client,action,code='',csrf=True):
        return client.post('/api/accounts/session-link',json={'action':action,'code':code},
            headers={'X-ZAR-Business-CSRF':'TEST'} if csrf else {},base_url=BASE)

    def proof(self,status='CONNECTED'):
        return patch.object(accounts.AccountConnectionRegistry,'reverify',return_value={'status':status,'account_identity':'fixture@example.invalid'})

    def test_device_code_explicitly_links_same_scope_and_preserves_files(self):
        source=Path(self.tmp.name)/'source.json';source.write_text('original fixture')
        mobile=self.app.test_client()
        with mobile.session_transaction() as s:s.update(zar_auth=True,zar_user_id='mobile',business_csrf='TEST')
        with self.proof():
            issued=self.pair_request(self.owner,'create')
            self.assertEqual(issued.status_code,200)
            code=issued.json['code'];self.assertGreaterEqual(len(code),32)
            self.assertNotIn(code.encode(),Path(self.tmp.name,'oauth_transactions.sqlite3').read_bytes())
            result=self.pair_request(mobile,'redeem',code)
            self.assertEqual(result.status_code,200)
            with mobile.session_transaction() as s:
                self.assertEqual(s['zar_user_id'],'owner');self.assertTrue(s['zar_auth'])
                self.assertNotEqual(s['business_csrf'],'TEST')
            self.assertEqual(self.pair_request(self.owner,'redeem',code).status_code,400)
        self.assertEqual(source.read_text(),'original fixture')
        self.assertEqual(issued.headers['Cache-Control'],'no-store')

    def test_device_link_requires_authentication_and_csrf(self):
        with self.proof() as proof:
            self.assertEqual(self.pair_request(self.owner,'create',csrf=False).status_code,403)
            self.assertEqual(self.pair_request(self.app.test_client(),'create').status_code,401)
            proof.assert_not_called()

    def test_unverified_source_cannot_issue_or_redeem(self):
        with self.proof('ERROR'):
            self.assertEqual(self.pair_request(self.owner,'create').status_code,409)
            code='X'*32
            transport.put('device:'+hashlib.sha256(code.encode()).hexdigest(),{'scope':'other'})
            self.assertEqual(self.pair_request(self.owner,'redeem',code).status_code,409)
            with self.owner.session_transaction() as s:self.assertEqual(s['zar_user_id'],'owner')

    def test_expired_or_guessed_device_code_cannot_change_session(self):
        code='Y'*32
        transport.put('device:'+hashlib.sha256(code.encode()).hexdigest(),{'scope':'other'},ttl=-1)
        with self.proof() as proof:
            self.assertEqual(self.pair_request(self.owner,'redeem',code).status_code,400)
            self.assertEqual(self.pair_request(self.owner,'redeem','Z'*32).status_code,400)
            proof.assert_not_called()
        with self.owner.session_transaction() as s:self.assertEqual(s['zar_user_id'],'owner')

    def test_webview_never_consumes_handoff_before_chrome(self):
        ident=transport.begin('owner','google','/connect/google?force=1')
        url='/oauth/accounts/start/'+ident
        external=self.app.test_client()
        response=external.get(url,base_url=BASE,headers={'User-Agent':'Mozilla/5.0 (Linux; Android 14; Pixel; wv) Version/4.0 Chrome/130 Mobile'})
        self.assertEqual(response.status_code,200);self.assertNotIn('intent://',response.text)
        self.assertIn('Chrome',response.text)
        self.assertEqual(external.get(url,base_url=BASE).status_code,302)

    def test_saved_credential_failure_is_not_reported_as_missing(self):
        from app import cloud_auth
        saved=Path(self.tmp.name)/'google_token.json';saved.write_text('DO_NOT_REMOVE')
        with patch.object(cloud_auth,'get_credentials',return_value=None),patch.object(cloud_auth,'_token_file',return_value=saved):
            self.assertEqual(accounts.google('owner')['status'],'ERROR')
        self.assertEqual(saved.read_text(),'DO_NOT_REMOVE')

    def test_failed_verification_retains_last_known_identity_without_connected_state(self):
        previous={'account_connections':{'google':{'account_identity':'fixture@example.invalid','status':'CONNECTED'}}}
        registry=accounts.AccountConnectionRegistry('owner')
        with patch.object(accounts.holdings,'read',return_value=previous),patch.object(accounts.holdings,'write'),patch.object(registry,'notification'),patch.object(accounts,'google',return_value={'status':'ERROR'}):
            # Providers capture their adapters at construction.
            with patch.object(registry,'provider',return_value=accounts.Provider('google','Google','G','G',(),lambda s:{'status':'ERROR'})):
                result=registry.reverify('google')
        self.assertEqual(result['account_identity'],'fixture@example.invalid')
        self.assertEqual(result['status'],'ERROR')
