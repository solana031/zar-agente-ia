import os,tempfile,unittest
from unittest.mock import Mock,patch
from app import holdings,business_orchestration as control,identity_center
from app.revolut_business import RevolutBusinessAdapter,sync
from app.relayclaw_usage_sync import RelayClawUsageSync


class FinancialAdaptersTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'ZAR_DATA_DIR':self.tmp.name},clear=True);self.env.start();self.scope='adapter-fixture'
    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def session(self,data,code=200):
        session=Mock();session.get.return_value.status_code=code;session.get.return_value.json.return_value=data;return session
    def test_missing_auth_and_no_live_execution(self):
        adapter=RevolutBusinessAdapter(self.session([]))
        self.assertFalse(adapter.capabilities()['verified'])
        with self.assertRaises(ValueError):adapter.getAccounts()
        for action in ('executePayment','createPaymentDraft','cancelPayment'):
            with self.assertRaises(ValueError):getattr(adapter,action)({})
        self.assertEqual(len(holdings.read(self.scope).get('ledger',[])),0)
    def test_read_balance_distinct_from_accounting_and_sensitive_card_fields(self):
        with patch.dict(os.environ,{'REVOLUT_BUSINESS_ACCESS_TOKEN':'fixture-not-real'}):
            session=self.session([{'id':'account1','balance':12.3,'currency':'EUR','state':'active','pan':'sensitive-fixture','cvv':'fixture'}])
            adapter=RevolutBusinessAdapter(session);snapshot=sync(self.scope,adapter)
            self.assertTrue(snapshot['verified']);self.assertFalse(snapshot['payment'])
            self.assertNotIn('pan',snapshot['accounts'][0]);self.assertNotIn('cvv',adapter.getCards()[0])
            self.assertEqual(len(holdings.read(self.scope)['ledger']),0)
            self.assertTrue(session.get.call_args.kwargs['allow_redirects'] is False)
    def test_auth_failure_does_not_claim_connected(self):
        with patch.dict(os.environ,{'REVOLUT_BUSINESS_ACCESS_TOKEN':'fixture-not-real'}):
            with self.assertRaises(ValueError):sync(self.scope,RevolutBusinessAdapter(self.session({},401)))
            self.assertNotIn('financial_provider_snapshot',holdings.read(self.scope))
    def test_scoped_api_guard(self):
        for action in ('provider_sync','provider_funding','relayclaw_sync'):
            with self.assertRaises(ValueError):control.mutate(self.scope,action,{})
    def test_relay_money_dedup_no_quota_conversion(self):
        with patch.dict(os.environ,{'RELAYCLAW_USAGE_API_KEY':'fixture-not-real'}):
            row={'id':'usage1','status':'charged','amount':'0.588','currency':'CNY','timestamp':holdings._now()}
            session=self.session({'data':[row,{'id':'usage2','quota':45000,'type':2}]})
            job=RelayClawUsageSync(session);job.run(self.scope);job.run(self.scope)
            events=holdings.read(self.scope)['financial_events'];self.assertEqual(len(events),1);self.assertEqual(events[0]['business'],'media')
            self.assertEqual(job.run(self.scope)['rows_without_money'],1)
    def test_mp4_resolver_does_not_resolve_unrelated_failure(self):
        with patch('app.media_company._task',side_effect=ValueError('missing')):
            self.assertIsNone(identity_center.verified_existing_mp4(self.scope,'task 70d97071aec345f7 blocked'))
    def test_obsolete_mp4_action_resolves_only_with_file_proof(self):
        d=holdings.read(self.scope);center=identity_center.ensure(d)
        row=identity_center.queue(center,'DRAMACLAW','OBSERVED_BLOCKER','task 70d97071aec345f7 MP4 no generado',None,[])
        holdings.write(self.scope,d)
        with patch('app.media_company.status',return_value={'api_ready':True,'capabilities':{'configured':True}}),patch('app.identity_center.verified_existing_mp4',return_value=None):
            self.assertEqual(identity_center.operate(self.scope,'continue',{'id':row['id']})['status'],'ACTION_REQUIRED')
        with patch('app.media_company.status',return_value={'api_ready':True,'capabilities':{}}),patch('app.identity_center.verified_existing_mp4',return_value={'duration':5,'codec':'h264','size':124202}):
            result=identity_center.operate(self.scope,'continue',{'id':row['id']})
            self.assertEqual(result['status'],'DONE');self.assertIn('IndexTTS2 ERROR / OPTIONAL',result['verification'])
        with patch('app.media_company._task'),patch('app.media_company._read',return_value={'status':'FAILED'}):
            self.assertIsNone(identity_center.verified_existing_mp4(self.scope,'task 70d97071aec345f7 blocked'))

if __name__=='__main__':unittest.main()
