"""Focused Shadow integration regressions: real control functions, simulated broker."""
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from flask import session
import test_stonks_lifecycle as baseline
from app import stonks_agents, stonks_dataplane, stonks_shadow, stonks_selftest


class ShadowRouteTests(unittest.TestCase):
    def setUp(self):
        baseline.LifecycleTests.setUp(self)
        self.state.update(execution_mode='shadow',position_lifecycle_enabled=False)
        baseline.LifecycleTests.configure_worker(self)
        self.api.update(stonks_agents=stonks_agents, stonks_dataplane=stonks_dataplane,
                        stonks_shadow=stonks_shadow, stonks_selftest=stonks_selftest,
                        stonks_news=SimpleNamespace(get_context=Mock(return_value={})))
        self.api['_stonks_stream_plan']=Mock(return_value={})
        stonks_dataplane.PLANE.reset_runtime()
        self.no_network=patch('requests.post', side_effect=AssertionError('Network forbidden'))
        self.no_network.start(); self.addCleanup(self.no_network.stop)

    def test_manual_confirmation_cannot_bypass_shadow(self):
        with self.api['app'].test_request_context('/',method='POST',json={
                'symbol':'AAPL','strategy':'trend','signal':'BUY',
                'execute':True,'manual_confirmed':True}):
            session['zar_user_id']='test-owner'
            result=self.api['stonks_decision_api']().get_json()
        self.assertFalse(result['order_created'])
        self.assertTrue(any(c['code']=='SHADOW' and not c['passed'] for c in result['checks']))
        self.assertEqual(self.posts,[])

    def test_direct_order_endpoint_cannot_bypass_shadow(self):
        with self.api['app'].test_request_context('/',method='POST',json={
                'symbol':'AAPL','side':'buy','type':'limit','limit_price':100,'qty':0.1}):
            session['zar_user_id']='test-owner'
            result,status=self.api['stonks_alpaca_order_api']()
        self.assertEqual(status,409)
        self.assertIn('Shadow',result.get_json()['error'])

    def test_repeated_worker_signal_is_one_observation_across_restart(self):
        for _ in range(3):
            result=self.api['_stonks_engine_cycle']('test-owner')
            self.assertEqual(result['status'],'ok',result)
        self.assertEqual(self.posts,[])
        self.assertEqual(len(self.api['_stonks_read']()['shadow_log']),1)
        stonks_dataplane.PLANE.reset_runtime()
        self.api['_stonks_engine_cycle']('test-owner')
        self.assertEqual(len(self.api['_stonks_read']()['shadow_log']),1)
        self.api['_stonks_current_signal'].return_value=({'signal':'BUY','bar_time':'2026-09-28T10:01:00Z'},self.clock)
        stonks_dataplane.PLANE.reset_runtime()
        self.api['_stonks_engine_cycle']('test-owner')
        self.assertEqual(len(self.api['_stonks_read']()['shadow_log']),2)
        self.assertEqual(self.posts,[])


    def test_outcome_reads_all_pages_and_rejects_repeated_cursor(self):
        from datetime import datetime, timezone, timedelta
        start=datetime.now(timezone.utc)-timedelta(minutes=10)
        rows=[{'symbol':sym,'timestamp':start.isoformat(),'signal':'BUY','price':100}
              for sym in ('AAPL','MSFT')]
        bars=[{'t':(start+timedelta(minutes=i)).isoformat(),'h':102,'l':100,'c':101}
              for i in range(1,6)]
        fetch=Mock(side_effect=[{'bars':{'AAPL':bars},'next_page_token':'next'},
                                {'bars':{'MSFT':bars}}])
        self.api['_alpaca_market_request']=fetch
        state,_=self.api['_stonks_refresh_shadow_outcomes']({'shadow_log':rows},force=True)
        self.assertTrue(all('5' in e['outcomes'] for e in state['shadow_log']))
        self.assertEqual(fetch.call_args_list[1].kwargs['params']['page_token'],'next')
        self.api['_alpaca_market_request']=Mock(return_value={'bars':{},'next_page_token':'same'})
        with self.assertRaisesRegex(RuntimeError,'snapshot incompleto'):
            self.api['_stonks_refresh_shadow_outcomes']({'shadow_log':rows},force=True)


if __name__=='__main__': unittest.main()
