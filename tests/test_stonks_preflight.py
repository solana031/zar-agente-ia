"""Read-only preflight and the production START gate, entirely broker-mocked."""
import unittest
from unittest.mock import Mock
import test_stonks_controlled_lifecycle as controlled


class PreflightTests(unittest.TestCase):
    setUp = controlled.ControlledLifecycleTests.setUp
    call = controlled.ControlledLifecycleTests.call
    start = controlled.ControlledLifecycleTests.start
    state_on_disk = controlled.ControlledLifecycleTests.state_on_disk

    def preflight(self, symbol='AAPL'):
        return self.api['_stonks_lifecycle_preflight'](symbol)

    def test_ready_is_read_only(self):
        before=self.state_on_disk()
        self.assertEqual(self.preflight()['status'],'READY')
        self.assertEqual(self.posts,[])
        self.assertEqual(self.state_on_disk(),before)

    def test_null_or_malformed_heartbeat_never_authorizes_entry(self):
        initial=self.state_on_disk()
        for value in [None, True, 1, [], {}, '']:
            with self.subTest(value=value):
                self.api['_stonks_write']({**initial,'engine_last_run':value})
                result=self.preflight()
                self.assertEqual(result['status'],'UNVERIFIED')
                heartbeat=next(c for c in result['checks'] if c['code']=='HEARTBEAT')
                self.assertEqual(heartbeat['status'],'UNVERIFIED')
                self.assertEqual(self.start()[1],409)
                self.assertEqual(self.posts,[])
                self.assertEqual(self.state_on_disk()['position_ledger'],{})

    def test_local_blocks(self):
        initial=self.state_on_disk()
        for change in [{'paused':True},{'revoked':True},{'autonomous_engine':False},
                       {'engine_last_run':'2000-01-01T00:00:00+00:00'},
                       {'mode':'live'},{'execution_mode':'decision'},{'position_lifecycle_enabled':False},
                       {'max_trade_eur':.99},{'max_position_pct':.001},{'max_daily_loss_eur':0},
                       {'pending_entries':{'AAPL':{}}}]:
            with self.subTest(change=change):
                self.api['_stonks_write']({**initial,**change})
                self.assertEqual(self.preflight()['status'],'BLOCKED')
        self.api['_stonks_write'](initial)
        self.api['_stonks_engine_owner_write']('other')
        self.assertEqual(self.preflight()['status'],'BLOCKED')

    def test_account_and_asset_blocks(self):
        for mapping,field,value in [(self.clock,'is_open',False),(self.account,'status','CLOSED'),
            (self.account,'trading_blocked',True),(self.account,'account_blocked',True),
            (self.account,'buying_power','.99'),(self.account,'equity','0'),
            (self.account,'last_equity','10020'),(self.asset,'status','inactive'),
            (self.asset,'class','crypto'),(self.asset,'tradable',False),(self.asset,'fractionable',False)]:
            with self.subTest(field=field):
                old=mapping[field];mapping[field]=value
                self.assertEqual(self.preflight()['status'],'BLOCKED')
                mapping[field]=old

    def test_missing_and_failed_evidence_never_ready(self):
        for mapping,field in [(self.account,'trading_blocked'),(self.account,'equity'),(self.clock,'is_open'),(self.asset,'fractionable')]:
            old=mapping.pop(field)
            self.assertEqual(self.preflight()['status'],'UNVERIFIED')
            mapping[field]=old
        self.account['equity']='NaN'
        self.assertNotEqual(self.preflight()['status'],'READY')
        self.api['_alpaca_paper_request']=Mock(side_effect=TimeoutError('SECRET_DO_NOT_LOG'))
        result=self.preflight()
        self.assertEqual(result['status'],'UNVERIFIED')
        self.assertNotIn('SECRET_DO_NOT_LOG',str(result))

    def test_symbol_and_existing_state(self):
        self.assertEqual(self.preflight('../bad')['status'],'BLOCKED')
        self.positions=[{'symbol':'AAPL'}]
        self.assertEqual(self.preflight()['status'],'BLOCKED')
        self.positions=[]
        self.orders['manual']={'symbol':'AAPL','status':'new'}
        self.assertEqual(self.preflight()['status'],'BLOCKED')
        self.orders={}
        self.start()
        self.assertEqual(self.preflight()['status'],'BLOCKED')
        self.assertEqual(self.preflight('MSFT')['status'],'BLOCKED')

    def test_ready_then_blocked_at_start_and_client_bypass(self):
        self.assertEqual(self.preflight()['status'],'READY')
        self.account['trading_blocked']=True
        result,status=self.call('start',{'confirm':True,'symbol':'AAPL','request_id':self.request_id,'preflight':{'status':'READY'}})
        self.assertEqual(status,409)
        self.assertEqual(self.posts,[])

    def test_fresh_check_immediately_before_intent(self):
        original=self.api['_stonks_lifecycle_preflight']
        def changed(symbol):
            self.clock['is_open']=False
            return original(symbol)
        self.api['_stonks_lifecycle_preflight']=changed
        self.assertEqual(self.start()[1],409)
        self.assertEqual(self.state_on_disk()['position_ledger'],{})
        self.assertEqual(self.posts,[])


if __name__=='__main__':unittest.main()
