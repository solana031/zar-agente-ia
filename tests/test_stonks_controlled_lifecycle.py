"""Controlled lifecycle exercises the real Flask decision + worker using broker mocks."""
import copy
import uuid
import threading
import unittest
from flask import session
import test_stonks_lifecycle as baseline


class ControlledLifecycleTests(unittest.TestCase):
    position = baseline.LifecycleTests.position

    def setUp(self):
        baseline.LifecycleTests.setUp(self)
        self.account.update(status='ACTIVE', buying_power='10000',trading_blocked=False,account_blocked=False)
        self.state['engine_last_run']=baseline.lifecycle.now()
        self.api['_alpaca_paper_credentials']=lambda:('mock-key','mock-secret')
        self.asset = {'status':'active','tradable':True,'fractionable':True,'class':'us_equity'}
        baseline.LifecycleTests.configure_worker(self, signal='HOLD')
        broker = self.api['_alpaca_paper_request'].side_effect
        self.api['_alpaca_paper_request'].side_effect = lambda path, **kw: self.asset if path.startswith('/v2/assets/') else broker(path, **kw)
        self.request_id = str(uuid.uuid4())

    def call(self, endpoint, body):
        with self.api['app'].test_request_context('/api/stonks/lifecycle-test/'+endpoint, method='POST',json=body):
            session['zar_user_id']='test-owner'
            result=self.api['stonks_lifecycle_test_'+endpoint+'_api']()
            return (result[0].get_json(),result[1]) if isinstance(result,tuple) else (result.get_json(),200)

    def start(self, request_id=None):
        return self.call('start', {'confirm':True,'symbol':'AAPL','request_id':request_id or self.request_id})

    def state_on_disk(self):
        return self.api['_stonks_read']()

    def record(self):
        return next(r for r in self.state_on_disk()['position_ledger'].values() if r.get('purpose')=='TEST_LIFECYCLE')

    def cycle(self):
        return self.api['_stonks_engine_cycle']('test-owner')

    def fill(self):
        cid=self.record()['client_order_id']
        self.orders[cid].update(qty='0.01',filled_qty='0.01',status='filled',filled_avg_price='100',filled_at=baseline.lifecycle.now())
        self.position(qty='0.01')
        self.cycle()

    def close(self, cid=None):
        return self.call('close', {'confirm':True,'id':cid or self.record()['client_order_id']})

    def finish(self):
        self.close();self.cycle()
        cid=self.posts[-1]['client_order_id']
        self.orders[cid].update(status='filled',filled_qty='0.01',filled_avg_price='100')
        self.positions=[]
        self.cycle()

    def audit_events(self):
        return [r['event'] for r in self.api['_stonks_audit_read'](200)]

    def test_start_minimal_notional_and_real_ownership_path(self):
        result,status=self.start()
        self.assertEqual(status,202)
        self.assertEqual(result['lifecycle_test']['status'],'ESPERANDO_FILL')
        self.assertEqual(self.posts[0]['notional'],'1.00')
        self.assertNotIn('qty',self.posts[0])
        record=self.record()
        self.assertTrue(record['baseline_flat'])
        self.assertEqual(record['origin'],'TEST_LIFECYCLE')
        self.assertEqual(record['strategy'],'TEST_LIFECYCLE')
        self.assertEqual(record['client_order_id'],self.posts[0]['client_order_id'])
        self.assertIn('DECISIÓN',self.audit_events())
        self.assertIn('TEST_LIFECYCLE_STARTED',self.audit_events())
        self.assertIn('TEST_ENTRY_REQUESTED',self.audit_events())

    def test_fill_detect_close_and_all_audit_milestones(self):
        self.start();self.fill()
        state=self.state_on_disk();row=state['managed_positions']['AAPL']
        self.assertEqual(row['entry_price'],100)
        self.assertEqual(row['stop_price'],99)
        self.assertEqual(row['take_price'],102)
        self.assertEqual(row['unrealized_pl'],0)
        self.assertEqual(baseline.lifecycle.test_view(state)['status'],'POSICION_DETECTADA')
        self.finish()
        view=baseline.lifecycle.test_view(self.state_on_disk())
        self.assertEqual(view['status'],'OK')
        self.assertFalse(view['active'])
        self.assertEqual(len(self.posts),2)
        for event in ['TEST_LIFECYCLE_STARTED','TEST_ENTRY_REQUESTED','TEST_POSITION_DETECTED',
                      'TEST_CLOSE_REQUESTED','TEST_POSITION_CLOSED','TEST_LIFECYCLE_OK']:
            self.assertEqual(self.audit_events().count(event),1,event)
        self.assertEqual(self.state_on_disk()['stop_loss_pct'],1)
        self.assertEqual(self.state_on_disk()['take_profit_pct'],2)

    def test_second_start_and_repeated_close_do_not_duplicate(self):
        self.start()
        self.assertEqual(self.start()[1],200)
        self.assertEqual(self.start(str(uuid.uuid4()))[1],409)
        self.fill()
        self.close();self.close();self.cycle();self.close();self.cycle()
        self.assertEqual(len(self.posts),2)
        self.assertEqual(len(self.record()['exits']),1)

    def test_restart_recovers_entry_and_close(self):
        self.start();self.fill();self.close()
        old=self.api
        self.api=baseline.control_plane(self.temp.name)
        for key in ['_alpaca_paper_request','_alpaca_market_request','_stonks_current_signal','_stonks_submit_paper_order']:
            self.api[key]=old[key]
        self.cycle();self.cycle()
        self.assertEqual(len(self.posts),2)
        self.assertEqual(baseline.lifecycle.test_view(self.state_on_disk())['status'],'ESPERANDO_CIERRE')

    def test_submit_timeout_recovers_without_second_entry(self):
        submit=self.api['_stonks_submit_paper_order'].side_effect
        def uncertain(body):
            submit(body)
            raise TimeoutError('must never be logged')
        self.api['_stonks_submit_paper_order'].side_effect=uncertain
        result,status=self.start()
        self.assertEqual(status,409)
        self.assertTrue(result['lifecycle_test']['active'])
        self.assertEqual(self.start(str(uuid.uuid4()))[1],409)
        self.api['_stonks_submit_paper_order'].side_effect=submit
        self.fill()
        self.assertEqual(len(self.posts),1)
        self.assertIn('TEST_LIFECYCLE_ERROR',self.audit_events())
        self.assertEqual(baseline.lifecycle.test_view(self.state_on_disk())['status'],'POSICION_DETECTADA')

    def test_close_timeout_then_fill_recovers_complete_audit(self):
        self.start();self.fill();self.close()
        submit=self.api['_stonks_submit_paper_order'].side_effect
        def uncertain(body):
            order=submit(body)
            order.update(status='filled',filled_qty='0.01')
            self.positions=[]
            raise TimeoutError()
        self.api['_stonks_submit_paper_order'].side_effect=uncertain
        self.cycle()
        self.assertEqual(baseline.lifecycle.test_view(self.state_on_disk())['status'],'OK')
        self.assertIn('TEST_CLOSE_REQUESTED',self.audit_events())
        self.assertEqual(len(self.posts),2)

    def test_start_gates_and_account_connection(self):
        initial=self.state_on_disk()
        for changes in [{'paused':True},{'revoked':True},{'autonomous_engine':False},
                        {'position_lifecycle_enabled':False},{'mode':'live'},{'execution_mode':'decision'}]:
            with self.subTest(changes=changes):
                self.api['_stonks_write']({**initial,**changes})
                self.assertEqual(self.start()[1],409)
                self.assertEqual(self.posts,[])
        self.api['_stonks_write'](initial)
        self.account['status']='ACCOUNT_CLOSED'
        self.assertEqual(self.start()[1],409)
        self.assertEqual(self.posts,[])

    def test_pause_and_revoke_after_close_request_preserve_reconciliation(self):
        self.start();self.fill();self.close()
        for flags in [{'paused':True},{'revoked':True}]:
            state=self.state_on_disk();state.update(flags);self.api['_stonks_write'](state)
            self.assertEqual(self.close()[1],409)
            self.cycle()
            self.assertEqual(len(self.posts),1)
            self.assertTrue(self.state_on_disk()['engine_last_reconcile'])

    def test_risk_and_asset_guards(self):
        original=self.state_on_disk()
        for change in [{'max_trade_eur':0.99},{'max_daily_loss_eur':0},{'max_position_pct':0.001}]:
            self.api['_stonks_write']({**original,**change})
            self.assertEqual(self.start()[1],409)
        self.api['_stonks_write'](original)
        self.asset['fractionable']=False
        self.assertEqual(self.start()[1],409)
        self.assertEqual(self.posts,[])

    def test_manual_position_untouched_and_not_adopted(self):
        self.position(qty='1')
        self.assertEqual(self.start()[1],409)
        self.assertEqual(self.posts,[])
        self.assertEqual(self.state_on_disk()['position_ledger'],{})
        self.assertEqual(self.close('manual-position')[1],400)

    def test_manual_same_symbol_activity_blocks_test_close(self):
        self.start();self.fill();self.close()
        self.orders['external']={'id':'external','client_order_id':'external','symbol':'AAPL','side':'buy',
                                 'filled_qty':'1','status':'filled','submitted_at':baseline.lifecycle.now()}
        self.position(qty='1.01')
        self.cycle()
        self.assertEqual(len(self.posts),1)
        self.assertEqual(baseline.lifecycle.test_view(self.state_on_disk())['status'],'ERROR')

    def test_cannot_close_normal_owned_position_as_test(self):
        record=baseline.lifecycle.entry_intent(self.state,'AAPL','buy','2','trend','1Min')
        self.api['_stonks_write'](self.state)
        self.assertEqual(self.close(record['client_order_id'])[1],400)

    def test_entry_without_fill_never_enables_close(self):
        self.start();self.cycle()
        self.assertEqual(self.close()[1],409)
        self.assertFalse(baseline.lifecycle.test_view(self.state_on_disk())['can_close'])
        self.assertEqual(self.state_on_disk()['managed_positions'],{})

    def test_terminal_entry_without_fill_is_error_not_success(self):
        self.start()
        self.orders[self.record()['client_order_id']]['status']='rejected'
        self.cycle()
        view=baseline.lifecycle.test_view(self.state_on_disk())
        self.assertEqual(view['status'],'ERROR')
        self.assertFalse(view['active'])
        self.assertNotIn('TEST_LIFECYCLE_OK',self.audit_events())

    def test_replay_finished_request_never_starts_again(self):
        self.start();self.fill();self.finish()
        self.assertEqual(self.start()[1],200)
        self.assertEqual(len(self.posts),2)
        self.assertEqual(self.start(str(uuid.uuid4()))[1],202)
        self.assertEqual(len(self.posts),3)

    def test_confirmation_and_owner_required(self):
        self.assertEqual(self.call('start', {'symbol':'AAPL','request_id':self.request_id})[1],400)
        self.api['_stonks_engine_owner_write']('other-owner')
        self.assertEqual(self.start()[1],409)
        self.assertEqual(self.posts,[])

    def test_test_flag_cannot_be_injected_through_public_decision(self):
        with self.api['app'].test_request_context('/api/stonks/decision',method='POST',json={
                'symbol':'AAPL','signal':'BUY','execute':True,'lifecycle_test':True,'engine':True}):
            session['zar_user_id']='test-owner'
            self.api['stonks_decision_api']()
        self.assertEqual(self.posts,[])
        self.assertEqual(self.state_on_disk()['position_ledger'],{})

    def test_worker_error_retains_test_for_recovery(self):
        self.start();self.fill()
        self.api['_alpaca_paper_request'].side_effect=TimeoutError()
        self.cycle()
        view=baseline.lifecycle.test_view(self.state_on_disk())
        self.assertTrue(view['active'])
        self.assertEqual(view['status'],'ERROR')
        self.assertIn('TEST_LIFECYCLE_ERROR',self.audit_events())

    def test_zero_equity_does_not_bypass_risk_for_fixed_notional(self):
        self.account.update(equity='0',last_equity='0')
        self.assertEqual(self.start()[1],409)
        self.assertEqual(self.posts,[])

    def test_market_closed_blocks_start(self):
        self.clock['is_open']=False
        self.assertEqual(self.start()[1],409)
        self.assertEqual(self.posts,[])

    def test_simultaneous_starts_allow_only_one_test(self):
        results=[]
        threads=[threading.Thread(target=lambda:results.append(self.start(str(uuid.uuid4()))[1])) for _ in range(2)]
        for t in threads:t.start()
        for t in threads:t.join(timeout=5)
        self.assertEqual(sorted(results),[202,409])
        self.assertEqual(len(self.posts),1)

    def test_close_rechecks_risk_after_ui_request(self):
        self.start();self.fill();self.close()
        self.account['last_equity']='10020'
        self.cycle()
        self.assertEqual(len(self.posts),1)
        self.assertEqual(baseline.lifecycle.test_view(self.state_on_disk())['status'],'ERROR')
        self.assertIn('TEST_LIFECYCLE_ERROR',self.audit_events())

    def test_test_position_is_not_closed_by_strategy_signal(self):
        self.start();self.fill()
        self.api['_stonks_current_signal'].return_value=({'signal':'SELL','bar_time':'2026-09-29T10:00:00Z'},self.clock)
        self.cycle()
        self.assertEqual(len(self.posts),1)
        self.assertFalse(self.record().get('trigger'))


if __name__=='__main__':unittest.main()
