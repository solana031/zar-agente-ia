import os, tempfile, unittest
from unittest.mock import patch
from app import holdings, business_orchestration as control
from app.financial_events import ingest, summary, sync_existing
from app.financial_provider import FinancialProvider, execute_reserved, reconcile_payment

class FinancialEventsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'ZAR_DATA_DIR':self.tmp.name},clear=True);self.env.start();self.scope='financial-fixture'
    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def event(self, **values):
        return dict(provider='FixtureProvider',business='sites',amount='1.25',currency='EUR',timestamp=holdings._now(),source='AUTHENTICATED_FIXTURE',external_id='invoice-1',**values)
    def test_verified_idempotency_conflict_and_currency(self):
        e=self.event()
        with self.assertRaises(ValueError):ingest(self.scope,'cost',e)
        a=ingest(self.scope,'cost',e,provider_verified=True);self.assertEqual(a,ingest(self.scope,'cost',e,provider_verified=True))
        self.assertEqual(len(holdings.read(self.scope)['ledger']),1)
        with self.assertRaises(ValueError):ingest(self.scope,'cost',dict(e,amount='2'),provider_verified=True)
        ingest(self.scope,'cost',dict(e,external_id='invoice-2',currency='USD'),provider_verified=True)
        periods=summary(holdings.read(self.scope))['periods']['cost']['today'];self.assertEqual({r['currency'] for r in periods},{'EUR','USD'})
    def test_no_estimated_revenue_and_no_duplicate_received_ledger(self):
        with self.assertRaises(ValueError):ingest(self.scope,'revenue',self.event(),provider_verified=True)
        holdings.add_ledger(self.scope,'sites','revenue',5,source='adsense_received',reference='payment-1',verified=True)
        self.assertEqual(sync_existing(self.scope),1);self.assertEqual(sync_existing(self.scope),0)
        self.assertEqual(len(holdings.read(self.scope)['ledger']),1)
    def reservation(self):
        control.mutate(self.scope,'mode',{'mode':'ACTIVE'});control.mutate(self.scope,'deposit',{'amount':'20','reference':'fixture-only'})
        control.mutate(self.scope,'budget',{'business':'sites','assigned':'20','max_action':'10','max_day':'20','max_month':'20','currency':'EUR'})
        row=control.mutate(self.scope,'prepare',{'business':'sites','item':'fixture','provider':'fixture','currency':'EUR','price':'3','tax':'0'})['approvals'][-1]
        self.assertEqual(row['jev_decision']['decision'],'CONFIRM')
        control.mutate(self.scope,'approve',{'id':row['id'],'total':row['total'],'confirmed':True});return row
    def test_cancel_releases_and_disabled_provider_never_executes(self):
        row=self.reservation()
        with self.assertRaises(ValueError):execute_reserved(self.scope,row['id'],FinancialProvider(),confirmed=True)
        control.mutate(self.scope,'cancel',{'id':row['id']});self.assertEqual(control.view(self.scope)['wallet']['balances']['EUR']['committed'],'0')
    def test_definitive_provider_failure_releases_no_cost(self):
        class Fixture(FinancialProvider):
            def capabilities(self):return {'verified':True,'payment':True}
            def createPayment(self,*args,**kw):return {'status':'FAILED','definitive':True}
        row=self.reservation();result=execute_reserved(self.scope,row['id'],Fixture(),confirmed=True)
        self.assertEqual(result['state'],'FAILED');self.assertEqual(control.view(self.scope)['wallet']['balances']['EUR']['committed'],'0');self.assertEqual(len(holdings.read(self.scope)['ledger']),1)
    def test_unknown_holds_until_verified_receipt_then_books_once(self):
        class Fixture(FinancialProvider):
            def capabilities(self):return {'verified':True,'payment':True}
            def createPayment(self,*args,**kw):raise TimeoutError()
            def paymentStatus(self,*args):return {'verified':True,'status':'PAID','provider':'FixtureProvider','amount':'3','currency':'EUR','timestamp':holdings._now(),'external_id':'charge-1'}
        row=self.reservation();p=Fixture();execute_reserved(self.scope,row['id'],p,confirmed=True)
        with self.assertRaises(ValueError):control.mutate(self.scope,'cancel',{'id':row['id']})
        self.assertEqual(reconcile_payment(self.scope,row['id'],p)['state'],'EXECUTED');reconcile_payment(self.scope,row['id'],p)
        self.assertEqual(len(holdings.read(self.scope)['ledger']),2);self.assertEqual(control.view(self.scope)['wallet']['balances']['EUR']['committed'],'0')

if __name__=='__main__':unittest.main()
