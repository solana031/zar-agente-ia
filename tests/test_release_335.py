"""Capital, identity, dynamic graph and encrypted OAuth, with zero provider writes."""
import json
import os
import shutil
import unittest
import uuid
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from app import holdings,trading_capital as capital,business_orchestration as control
from app import identity_provisioning as identity,orchestration_map as graph,oauth_vault


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(__file__).resolve().parents[1];self.tmp=self.root/('zar-335-test-'+uuid.uuid4().hex);self.tmp.mkdir()
        self.env=patch.dict(os.environ,{'ZAR_DATA_DIR':str(self.tmp)},clear=True);self.env.start();self.scope='offline-335'
        control.mutate(self.scope,'deposit',{'amount':'100','currency':'USD','reference':'offline'})
    def tearDown(self):
        self.env.stop();assert self.tmp.resolve().is_relative_to(self.root);shutil.rmtree(self.tmp)
    def snapshot(self):return {'status':'ACTIVE','currency':'USD','equity':'1000'},[],[]
    def move(self,action='assign',amount='20',tid=None,**kwargs):
        return capital.move(self.scope,{'action':action,'amount':amount,'currency':'USD','confirmed':True,'transaction_id':tid or uuid.uuid4().hex,'reason':'Offline test',**kwargs},self.snapshot)
    def test_transfer_dedup_and_conflicting_retry(self):
        tid=uuid.uuid4().hex;first=self.move(tid=tid);self.assertEqual(self.move(tid=tid),first)
        self.assertEqual(Decimal(capital.view(self.scope)['assigned']),20)
        self.assertEqual(Decimal(control.wallet(holdings.read(self.scope))['balances']['USD']['available']),80)
        with self.assertRaises(ValueError):self.move(amount='21',tid=tid)
        self.assertEqual(first['status'],'CONFIRMED');self.assertEqual(len(first['events']),2)
        for key in ('timestamp','user','balance_before','balance_after','source','destination','reason'):self.assertIn(key,first)
    def test_returns_and_reverse_conserve_wallet(self):
        row=self.move();self.move('return','5');self.assertEqual(Decimal(capital.view(self.scope)['assigned']),15)
        with self.assertRaises(ValueError):self.move('return','16')
        other=self.move(amount='20');self.move('reverse','20',reverses=other['transaction_id'])
        transactions=capital.view(self.scope)['transactions'];self.assertEqual(next(r for r in transactions if r['transaction_id']==other['transaction_id'])['status'],'REVERSED')
        self.move('return','15');self.assertEqual(Decimal(capital.view(self.scope)['wallet_total_available']),100)
    def test_business_revenue_is_not_auto_eligible(self):
        self.move(amount='100')
        holdings.add_ledger(self.scope,'commerce','revenue',1000,currency='USD',reference='offline-revenue',source='offline')
        self.assertEqual(Decimal(capital.view(self.scope)['wallet_available']),0)
        with self.assertRaises(ValueError):self.move(amount='1')
    def test_failed_provider_and_exposed_account_never_release(self):
        self.move()
        with patch.object(self,'snapshot',return_value=({'status':'ACTIVE','currency':'USD'},[{'symbol':'AAPL'}],[])):
            with self.assertRaises(ValueError):self.move('return','20')
        with patch.object(self,'snapshot',side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):self.move()
        self.assertEqual(Decimal(capital.view(self.scope)['assigned']),20)
        self.assertEqual(capital.view(self.scope)['transactions'][0]['status'],'FAILED')
    def test_concurrent_allocations_cannot_overdraw(self):
        def attempt(_):
            try:self.move(amount='20');return True
            except ValueError:return False
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(attempt,range(12)))
        self.assertEqual(sum(results),5);self.assertEqual(Decimal(capital.view(self.scope)['assigned']),100)
        self.assertEqual(Decimal(capital.view(self.scope)['wallet_available']),0)
    def test_order_budget_and_exits(self):
        self.move(amount='100');d=holdings.read(self.scope)
        capital.check_order(d,{'symbol':'AAPL','qty':'1','side':'buy'},[],[],80)
        with self.assertRaises(ValueError):capital.check_order(d,{'symbol':'AAPL','qty':'2','side':'buy'},[],[],80)
        with self.assertRaises(ValueError):capital.check_order(d,{'symbol':'AAPL','qty':'1','side':'buy'},[],[{}],80)
        capital.check_order(d,{'symbol':'AAPL','qty':'1','side':'sell'},[{'symbol':'AAPL','qty':'1','market_value':'200'}],[{}],1)
    def test_currency_and_user_separation(self):
        with self.assertRaises(ValueError):self.move(currency='EUR')
        self.move();self.assertEqual(Decimal(capital.view('other')['assigned']),0)
    def plan(self):return identity.operate(self.scope,'prepare',{'service':'GOOGLE','identity':'zar.offline@gmail.com','desired_name':'zar.offline'})
    def test_signup_stops_for_human_and_oauth_does_not_fake_active(self):
        plan=self.plan();self.assertEqual(plan['status'],'NOT_CREATED')
        started=identity.operate(self.scope,'start',{'id':plan['id']});self.assertEqual(started['status'],'HUMAN_ACTION_REQUIRED')
        with patch('app.gmail.is_connected',return_value=False):
            self.assertEqual(identity.operate(self.scope,'verify',{'id':plan['id']})['status'],'HUMAN_ACTION_REQUIRED')
        self.assertIsNone(identity.view(self.scope)['base_identity'])
        self.assertTrue(all(x['availability']=='NOT_VERIFIED_BY_GOOGLE' for x in identity.alternatives('zar.office')))
    def test_google_identity_requires_matching_real_profile(self):
        plan=self.plan()
        with patch('app.gmail.is_connected',return_value=True),patch('app.gmail.gmail_status',return_value={'email':'other@gmail.com'}):
            with self.assertRaises(ValueError):identity.operate(self.scope,'verify',{'id':plan['id']})
        with patch('app.gmail.is_connected',return_value=True),patch('app.gmail.gmail_status',return_value={'email':'zar.offline@gmail.com'}):
            r=identity.operate(self.scope,'verify',{'id':plan['id']});self.assertEqual(r['status'],'ACTIVE')
        saved=holdings.read(self.scope)['orchestration']['accounts'][0];self.assertEqual(saved['secret_reference'],'GOOGLE_OAUTH_SCOPED')
        self.assertEqual(identity.view(self.scope)['base_identity'],'zar.offline@gmail.com')
    def test_no_plain_credentials_in_account_plans(self):
        with self.assertRaises(ValueError):identity.operate(self.scope,'prepare',{'service':'GOOGLE','password':'offline'})
        with self.assertRaises(ValueError):identity.operate(self.scope,'prepare',{'service':'UNKNOWN'})
    def test_oauth_ciphertext_and_tamper_detection(self):
        payload=json.dumps({'token':'offline-token','refresh_token':'offline-refresh'})
        encoded=oauth_vault.encode(payload,self.tmp);self.assertNotIn('offline-token',encoded)
        self.assertEqual(oauth_vault.decode(encoded,self.tmp),json.loads(payload))
        value=json.loads(encoded);value['ciphertext']=value['ciphertext'][:20]+'x'+value['ciphertext'][21:]
        with self.assertRaises(Exception):oauth_vault.decode(json.dumps(value),self.tmp)
        self.assertEqual(oauth_vault.decode(payload,self.tmp),json.loads(payload))
    def test_dynamic_graph_and_view_persistence_are_scoped(self):
        d=holdings.read(self.scope);o=control.ensure(d);o['agents']['dynamic']={'id':'dynamic','name':'Future Agent','parent':'CommerceOrchestrator','domain':'commerce','state':'IDLE','current_tasks':['offline']}
        result=graph.graph({'agents':[{'id':'zar_supervisor'}],'edges':[]},d)
        node=next(a for a in result['agents'] if a['id']=='dynamic');self.assertEqual(node['parent'],'CommerceOrchestrator')
        saved=graph.save(self.scope,{'zoom':.001,'pan_x':125,'pan_y':230,'section':'commerce','filters':['commerce']})
        self.assertEqual(holdings.read(self.scope)['map_view'],saved);self.assertNotIn('map_view',holdings.read('other'))
        for zoom in (0,float('nan'),1001):
            with self.assertRaises(ValueError):graph.save(self.scope,{'zoom':zoom})
    def test_google_tokens_are_encrypted_and_legacy_migrates(self):
        from app import cloud_auth
        from google.oauth2.credentials import Credentials
        creds=Credentials(token='offline-token',refresh_token='offline-refresh',client_id='offline-id',client_secret='offline-client',token_uri='https://oauth2.googleapis.com/token')
        with patch.object(cloud_auth,'DATA_DIR',self.tmp):
            cloud_auth._save_credentials(creds,user_id='mock-google')
            path=cloud_auth._token_file('mock-google')
            self.assertNotIn('offline-refresh',path.read_text())
            self.assertEqual(cloud_auth.get_credentials(auto_refresh=False,user_id='mock-google').token,'offline-token')
            path.write_text(creds.to_json())
            self.assertEqual(cloud_auth.get_credentials(auto_refresh=False,user_id='mock-google').token,'offline-token')
            self.assertEqual(json.loads(path.read_text())['format'],'ZAR_OAUTH_ENCRYPTED_V1')
            self.assertIsNone(cloud_auth.get_credentials(auto_refresh=False,user_id='other'))
    def test_slow_research_never_blocks_safety_cycle(self):
        from app import stonks_news
        entered=threading.Event();release=threading.Event()
        def slow(*args,**kwargs):entered.set();release.wait(2);return {'ok':False}
        with patch.object(stonks_news,'get_context',side_effect=slow):
            start=time.monotonic();result=stonks_news.cached_context('ZZZOFFLINE')
            self.assertLess(time.monotonic()-start,.5)
            self.assertTrue(entered.wait(1));self.assertTrue(result['refresh_pending'])
            self.assertIsNone(result['sentiment'])
            release.set()

    def test_google_plan_survives_matching_oauth_scope_change_only(self):
        row=identity.operate(self.scope,'prepare',{'service':'GOOGLE','identity':'zar.mock@gmail.com'})
        identity.operate(self.scope,'human_completed',{'id':row['id'],'identity':'zar.mock@gmail.com','confirmed':True})
        identity.link_oauth_plan(self.scope,'other-login','different@gmail.com')
        self.assertEqual(identity.view('other-login')['plans'],[])
        identity.link_oauth_plan(self.scope,'matching-login','zar.mock@gmail.com')
        identity.link_oauth_plan(self.scope,'matching-login','zar.mock@gmail.com')
        self.assertEqual(len(identity.view('matching-login')['plans']),1)
        self.assertEqual(identity.view('matching-login')['plans'][0]['status'],'VERIFYING')
        self.assertNotIn('trading_capital',holdings.read('matching-login'))

    def test_youtube_oauth_migration_remains_readable_and_encrypted(self):
        from app import youtube_auth
        from google.oauth2.credentials import Credentials
        path=self.tmp/'youtube_token.json'
        creds=Credentials(token='offline-youtube',refresh_token='offline-refresh',token_uri='https://oauth2.googleapis.com/token',client_id='offline-id',client_secret='offline-secret',scopes=[youtube_auth.YOUTUBE_SCOPE])
        with patch.object(youtube_auth,'DATA_DIR',self.tmp),patch.object(youtube_auth,'TOKEN_FILE',path):
            youtube_auth._save_credentials(creds)
            self.assertNotIn('offline-youtube',path.read_text())
            self.assertEqual(youtube_auth.get_credentials(auto_refresh=False).token,'offline-youtube')
            path.write_text(creds.to_json())
            self.assertEqual(youtube_auth.get_credentials(auto_refresh=False).token,'offline-youtube')
            self.assertEqual(json.loads(path.read_text())['format'],'ZAR_OAUTH_ENCRYPTED_V1')


if __name__=='__main__':unittest.main()
