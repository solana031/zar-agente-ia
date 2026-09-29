"""Paper-only lifecycle and existing worker integration tests. No network is used.

The Flask control-plane functions are compiled from main.py's AST to avoid
starting unrelated OAuth/AI services and background workers during unit tests.
"""
import ast
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock
from functools import wraps
from contextlib import contextmanager
from datetime import datetime, timezone
import uuid
from flask import Flask, session, request, jsonify

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('lifecycle', ROOT / 'app/stonks_lifecycle.py')
lifecycle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lifecycle)


def control_plane(directory):
    app = Flask('lifecycle-test')
    app.secret_key = 'test-only'
    ns = dict(app=app, Path=Path, os=os, json=json, threading=threading, wraps=wraps,
              contextmanager=contextmanager, uuid=uuid, datetime=datetime, timezone=timezone,
              stonks_lifecycle=lifecycle, session=session, request=request, jsonify=jsonify,
              _STONKS_DIR=Path(directory), _STONKS_LOCK=threading.RLock(),
              _STONKS_LOCK_DEPTH=threading.local(), requests=Mock())
    tree = ast.parse((ROOT / 'app/main.py').read_text(encoding='utf-8-sig'))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and
             (n.name.startswith(('_stonks_', 'stonks_', '_alpaca_')) or n.name == '_user_scope_id')]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'app/main.py', 'exec'), ns)
    return ns


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.api = control_plane(self.temp.name)
        self.context = self.api['app'].test_request_context('/')
        self.context.push()
        self.addCleanup(self.context.pop)
        session['zar_user_id'] = 'test-owner'
        self.state = self.api['_stonks_default']()
        self.state.update(paused=False, revoked=False, autonomous_engine=True,
                          position_lifecycle_enabled=True, execution_mode='paper_auto',
                          max_trade_eur=1000, max_position_pct=100, max_daily_loss_eur=10)
        self.orders = {}
        self.positions = []
        self.events = []
        self.posts = []
        self.cancels = []
        self.clock = {'is_open': True}
        self.account = {'equity':'10000', 'last_equity':'10000'}
        self.save = self.api['_stonks_write']

    def entry(self, side='buy', filled='2', status='filled', price=100):
        record = lifecycle.entry_intent(self.state, 'AAPL', side, '2', 'trend', '1Min')
        cid = record['client_order_id']
        self.orders[cid] = dict(id='entry-id', client_order_id=cid, symbol='AAPL', side=side,
            qty='2', filled_qty=filled, status=status, submitted_at=record['submitted_at'],
            updated_at=record['submitted_at'], filled_at=record['submitted_at'] if status=='filled' else None)
        if float(filled):
            self.position(side, filled, price)
        self.save(self.state)
        return record

    def position(self, side='buy', qty='2', price=100):
        sign = 1 if side=='buy' else -1
        self.positions = [dict(symbol='AAPL', side='long' if sign==1 else 'short',
            qty=str(float(qty)*sign), avg_entry_price='100', current_price=str(price),
            market_value=str(float(qty)*price*sign), unrealized_pl=str((price-100)*float(qty)*sign),
            unrealized_plpc=str((price-100)/100*sign))]

    def submit(self, body):
        # Verify durable intent exists BEFORE the mock broker sees the order.
        disk = self.api['_stonks_read']()
        self.assertTrue(any(body['client_order_id']==i['client_order_id']
            for r in disk['position_ledger'].values() for i in r['exits']))
        self.posts.append(copy.deepcopy(body))
        order = dict(body, id='exit-'+str(len(self.posts)), status='new', filled_qty='0', submitted_at=lifecycle.now())
        self.orders[body['client_order_id']] = order
        return order

    def cycle(self, submit=None, lookup=None):
        return lifecycle.manage(self.state, self.positions, list(self.orders.values()),
            lookup or (lambda cid:self.orders.get(cid)), submit or self.submit, self.save,
            lambda event, detail:self.events.append((event,detail)), lambda:self.account, self.clock,
            cancel=lambda oid:self.cancels.append(oid))

    def row(self):
        return self.state['managed_positions']['AAPL']

    def test_long_short_sl_tp(self):
        for side, price, trigger, close_side in [('buy',98,'SL','sell'),('buy',103,'TP','sell'),
                                                ('sell',102,'SL','buy'),('sell',97,'TP','buy')]:
            with self.subTest(side=side, trigger=trigger):
                self.state['position_ledger']={}; self.state['managed_positions']={}
                self.orders={}; self.posts=[]; self.events=[]
                self.entry(side=side,price=price)
                self.cycle()
                self.assertEqual(self.posts[0]['side'],close_side)
                self.assertEqual(self.row()['status'],'CERRANDO_'+trigger)
                self.assertEqual(self.row()['entry_price'],100)
                self.assertEqual(self.row()['stop_price'],99 if side=='buy' else 101)
                self.assertEqual(self.row()['take_price'],102 if side=='buy' else 98)
                self.assertTrue({e for e,_ in self.events}>={'POSITION_DETECTED','POSITION_PROTECTED',trigger+'_TRIGGERED','CLOSE_REQUESTED'})

    def test_manual_position_not_managed(self):
        self.position(price=98)
        self.cycle()
        self.assertEqual(self.state['managed_positions'],{})
        self.assertEqual(self.posts,[])

    def test_submitted_not_filled_is_not_position(self):
        self.entry(filled='0',status='new')
        self.cycle()
        self.assertEqual(self.state['managed_positions'],{})
        self.assertEqual(self.posts,[])

    def test_partial_fill_cancel_remaining_then_close_actual_qty(self):
        record=self.entry(filled='0.5',status='partially_filled',price=98)
        self.cycle()
        self.assertEqual(self.row()['qty'],'0.5')
        self.assertEqual(self.posts,[])
        self.assertEqual(self.cancels,['entry-id'])
        self.orders[record['client_order_id']]['status']='canceled'
        self.cycle()
        self.assertEqual(float(self.posts[0]['qty']),0.5)

    def test_no_duplicate_pending_close_and_restart(self):
        self.entry(price=98)
        self.cycle()
        cid=self.posts[0]['client_order_id']
        for _ in range(4):self.cycle()
        self.assertEqual(len(self.posts),1)
        self.state=self.api['_stonks_read']()  # simulate new process state loaded from disk
        self.cycle()
        self.assertEqual(len(self.posts),1)
        self.orders[cid].update(status='filled',filled_qty='2')
        self.positions=[]
        self.cycle()
        self.assertEqual(self.row()['status'],'CERRADA')
        self.cycle()
        self.assertEqual(sum(e=='POSITION_CLOSED' for e,_ in self.events),1)

    def test_post_timeout_accepted_recovers_by_id(self):
        self.entry(price=98)
        def timeout(body):
            self.submit(body)
            raise TimeoutError('sensitive broker text must not be logged')
        self.cycle(submit=timeout)
        self.assertEqual(self.row()['status'],'ERROR')
        self.state=self.api['_stonks_read']()
        self.cycle()
        self.assertEqual(len(self.posts),1)
        self.assertEqual(self.row()['status'],'CERRANDO_SL')
        self.assertNotIn('sensitive',json.dumps(self.events))

    def test_crash_before_close_post_reuses_persisted_id(self):
        self.entry(price=98)
        attempted=[]
        def fail(body):
            attempted.append(body['client_order_id'])
            raise TimeoutError()
        self.cycle(submit=fail)
        self.state=self.api['_stonks_read']()
        self.cycle()
        self.assertEqual(self.posts[0]['client_order_id'],attempted[0])

    def test_pause_revoke_disable_and_closed_market_observe_only(self):
        self.entry(price=98)
        for flags in [{'paused':True},{'revoked':True},{'autonomous_engine':False},
                      {'position_lifecycle_enabled':False},{'execution_mode':'decision'}]:
            original=copy.deepcopy(self.state)
            self.state.update(flags)
            self.cycle()
            self.assertEqual(self.row()['status'],'ABIERTA')
            self.assertEqual(self.posts,[])
            self.assertEqual(self.row()['current_price'],98)
            self.state=original
        self.clock['is_open']=False
        self.cycle()
        self.assertEqual(self.posts,[])

    def test_daily_risk_and_chunked_size_limit(self):
        self.entry(price=98)
        self.account['last_equity']='10020'
        self.cycle()
        self.assertEqual(self.posts,[])
        self.assertIn('pérdida diaria',self.row()['reason'])
        self.account['last_equity']='10000'
        self.state['max_trade_eur']=25
        self.cycle()
        self.assertLessEqual(float(self.posts[0]['qty'])*98,25)
        close_event=next(detail for event,detail in self.events if event=='CLOSE_REQUESTED')
        self.assertEqual(close_event['qty'],self.posts[0]['qty'])

    def test_zero_limits_and_account_block(self):
        self.entry(price=98)
        for key in ['max_trade_eur','max_position_pct','max_daily_loss_eur']:
            original=self.state[key];self.state[key]=0
            self.cycle();self.assertEqual(self.posts,[])
            self.state[key]=original
        self.account['trading_blocked']=True
        self.cycle();self.assertEqual(self.posts,[])

    def test_manual_activity_quarantines_even_if_net_qty_matches(self):
        self.entry(price=98)
        self.orders['manual']=dict(symbol='AAPL',client_order_id='manual',side='buy',filled_qty='1',status='filled',submitted_at=lifecycle.now())
        self.cycle()
        self.assertEqual(self.posts,[])
        self.assertIn('Ownership ambiguo',self.row()['reason'])
        self.orders.pop('manual');self.cycle()
        self.assertEqual(self.posts,[])

    def test_quantity_mismatch_and_transient_missing_position_not_closed(self):
        self.entry(price=98)
        self.position(qty='3',price=98)
        self.cycle();self.assertEqual(self.row()['status'],'ERROR')
        self.positions=[];self.cycle()
        self.assertNotEqual(self.row()['status'],'CERRADA')
        self.assertEqual(self.posts,[])

    def test_temporary_lookup_error_does_not_erase_intent(self):
        record=self.entry(price=98)
        self.orders={}
        self.cycle(lookup=Mock(side_effect=TimeoutError()))
        self.assertEqual(self.row()['status'],'ERROR')
        self.assertIn(record['client_order_id'],self.state['position_ledger'])
        self.assertEqual(self.posts,[])

    def test_updated_real_average_entry_recalculates_levels(self):
        self.entry()
        self.positions[0]['avg_entry_price']='101'
        self.cycle()
        self.assertEqual(self.row()['stop_price'],99.99)
        self.assertEqual(self.row()['take_price'],103.02)

    def test_worker_reconciles_when_revoked_without_browser(self):
        self.entry(price=98)
        self.state.update(revoked=True,paused=True,autonomous_engine=False)
        self.save(self.state)
        def broker(path, **kwargs):
            if path=='/v2/positions':return self.positions
            if path=='/v2/clock':return self.clock
            if path=='/v2/account':return self.account
            if path=='/v2/orders':return list(self.orders.values()) if kwargs['params']['status']=='all' else []
            raise AssertionError(path)
        self.api['_alpaca_paper_request']=Mock(side_effect=broker)
        self.api['_stonks_submit_paper_order']=Mock(side_effect=AssertionError('must not send'))
        result=self.api['_stonks_engine_cycle']('test-owner')
        self.assertEqual(result['status'],'idle')
        saved=self.api['_stonks_read']()
        self.assertEqual(saved['managed_positions']['AAPL']['current_price'],98)
        self.assertTrue(saved['engine_last_reconcile'])
        self.api['_stonks_submit_paper_order'].assert_not_called()

    def test_worker_api_failure_retains_owned_position(self):
        self.entry();self.cycle()
        self.api['_alpaca_paper_request']=Mock(side_effect=TimeoutError())
        result=self.api['_stonks_engine_cycle']('test-owner')
        self.assertEqual(result['status'],'error')
        saved=self.api['_stonks_read']()
        self.assertEqual(saved['managed_positions']['AAPL']['status'],'ERROR')
        self.assertEqual(len(saved['position_ledger']),1)

    def test_atomic_state_corruption_fails_closed(self):
        self.api['_stonks_file']().write_text('{broken')
        with self.assertRaises(json.JSONDecodeError):self.api['_stonks_read']()

    def test_paper_adapter_fixed_endpoint_and_credentials(self):
        self.api['_alpaca_paper_credentials']=lambda:('mock-key','mock-secret')
        response=self.api['requests'].post.return_value
        response.ok=True;response.json.return_value={'id':'test-order'}
        self.api['_stonks_submit_paper_order']({'client_order_id':'test'})
        args,kwargs=self.api['requests'].post.call_args
        self.assertEqual(args[0],'https://paper-api.alpaca.markets/v2/orders')
        self.assertEqual(kwargs['headers']['APCA-API-KEY-ID'],'mock-key')

    def test_status_api_reports_lifecycle_without_replacing_controls(self):
        self.entry();self.cycle()
        self.api['_alpaca_paper_credentials']=lambda:('','')
        response=self.api['stonks_status_api']()
        data=response.get_json()
        self.assertEqual(data['managed_positions']['AAPL']['status'],'PROTEGIDA')
        self.assertEqual(data['managed_position_count'],1)

    def configure_worker(self, signal='BUY'):
        self.save(self.state)
        self.api['_stonks_engine_owner_write']('test-owner')
        self.api['_stonks_current_signal'] = Mock(return_value=({'signal':signal,'bar_time':'2026-09-28T10:00:00Z'},self.clock))
        self.api['_alpaca_market_request'] = Mock(return_value={'trade':{'p':100}})
        def broker(path, **kwargs):
            if path=='/v2/positions':return self.positions
            if path=='/v2/clock':return self.clock
            if path=='/v2/account':return self.account
            if path=='/v2/orders:by_client_order_id':return self.orders.get(kwargs['params']['client_order_id'])
            if path=='/v2/orders':
                return [o for o in self.orders.values() if kwargs['params']['status']=='all' or o['status'] not in lifecycle.TERMINAL]
            raise AssertionError(path)
        self.api['_alpaca_paper_request'] = Mock(side_effect=broker)
        def submit(body):
            disk=self.api['_stonks_read']()
            if body['client_order_id'].startswith('zar-e-'):
                self.assertIn(body['client_order_id'],disk['position_ledger'])
                self.assertTrue(disk['last_executed_signals'])
            self.posts.append(copy.deepcopy(body))
            order=dict(body,id='order-'+str(len(self.posts)),status='new',filled_qty='0',submitted_at=lifecycle.now())
            self.orders[body['client_order_id']]=order
            return order
        self.api['_stonks_submit_paper_order']=Mock(side_effect=submit)

    def test_worker_entry_persisted_before_post_and_recovered_after_timeout(self):
        self.configure_worker()
        submit=self.api['_stonks_submit_paper_order'].side_effect
        def uncertain(body):
            submit(body)
            raise TimeoutError()
        self.api['_stonks_submit_paper_order'].side_effect=uncertain
        self.api['_stonks_engine_cycle']('test-owner')
        self.assertEqual(len(self.posts),1)
        self.assertEqual(self.api['_stonks_read']()['managed_positions'],{})
        order=self.orders[self.posts[0]['client_order_id']]
        order.update(status='filled',filled_qty=order['qty'],filled_at=lifecycle.now())
        self.position(qty=order['qty'])
        self.api['_stonks_submit_paper_order'].side_effect=submit
        self.api['_stonks_engine_cycle']('test-owner')
        self.assertEqual(len(self.posts),1)
        self.assertEqual(self.api['_stonks_read']()['managed_positions']['AAPL']['status'],'PROTEGIDA')

    def test_worker_preserves_owned_strategy_sell_when_sl_tp_disabled(self):
        self.entry()
        self.state['position_lifecycle_enabled']=False
        self.configure_worker(signal='SELL')
        self.api['_stonks_engine_cycle']('test-owner')
        self.assertEqual(len(self.posts),1)
        self.assertEqual(self.posts[0]['side'],'sell')
        self.assertEqual(self.api['_stonks_read']()['managed_positions']['AAPL']['status'],'CERRANDO_SIGNAL')

    def test_worker_does_not_trade_manual_position(self):
        self.position()
        self.configure_worker(signal='SELL')
        self.api['_stonks_engine_cycle']('test-owner')
        self.assertEqual(self.posts,[])

    def test_worker_overlapping_cycles_send_only_one_entry(self):
        self.configure_worker()
        results=[]
        threads=[threading.Thread(target=lambda:results.append(self.api['_stonks_engine_cycle']('test-owner'))) for _ in range(3)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(timeout=5)
        self.assertEqual(len(results),3)
        self.assertEqual(len(self.posts),1)

    def test_revoke_preserves_owner_and_restart_observation(self):
        self.entry();self.configure_worker()
        self.api['stonks_revoke_api']()
        self.assertEqual(self.api['_stonks_engine_owner_read'](),'test-owner')
        self.api['_stonks_engine_cycle']('test-owner')
        self.assertEqual(self.posts,[])
        self.assertEqual(self.api['_stonks_read']()['managed_positions']['AAPL']['status'],'ABIERTA')

    def test_history_id_cursor_handles_equal_timestamps(self):
        page=[{'id':str(i),'submitted_at':'2026-09-28T10:00:00Z'} for i in range(500)]
        broker=Mock(side_effect=[page,[{'id':'older','submitted_at':'2026-09-28T09:00:00Z'}]])
        self.api['_alpaca_paper_request']=broker
        rows=self.api['_stonks_order_history']('2026-09-27T00:00:00Z')
        self.assertEqual(len(rows),501)
        params=broker.call_args_list[1].kwargs['params']
        self.assertEqual(params['before_order_id'],'499')
        self.assertNotIn('after',params)

    def test_history_repeated_page_fails_closed(self):
        page=[{'id':str(i),'submitted_at':'2026-09-28T10:00:00Z'} for i in range(500)]
        self.api['_alpaca_paper_request']=Mock(return_value=page)
        with self.assertRaises(RuntimeError):self.api['_stonks_order_history']('2026-09-27T00:00:00Z')

    def test_partial_close_updates_remaining_without_duplicate(self):
        self.entry(price=98);self.cycle()
        order=self.orders[self.posts[0]['client_order_id']]
        order.update(status='partially_filled',filled_qty='1')
        self.position(qty='1',price=98)
        self.cycle()
        self.assertEqual(len(self.posts),1)
        self.assertEqual(self.row()['qty'],'1.0')

    def test_rejected_close_does_not_resubmit(self):
        self.entry(price=98);self.cycle()
        self.orders[self.posts[0]['client_order_id']]['status']='rejected'
        self.cycle();self.cycle()
        self.assertEqual(len(self.posts),1)
        self.assertEqual(self.row()['status'],'ERROR')

    def test_missing_owned_symbol_from_watchlist_still_managed(self):
        self.entry(price=98)
        self.state['engine_symbols']=['MSFT']
        self.configure_worker(signal='HOLD')
        self.api['_stonks_engine_cycle']('test-owner')
        self.assertEqual(self.posts[0]['symbol'],'AAPL')

    def test_old_ambiguous_ownership_never_adopted(self):
        self.state['managed_positions']={'AAPL':{'entry_price':100,'qty':'2'}}
        self.position(price=98);self.save(self.state)
        self.api['_stonks_submit_paper_order']=Mock()
        self.api['_stonks_manage_positions']('test-owner',{'positions':self.positions,'open_orders':[],'history':[]},self.clock)
        self.api['_stonks_submit_paper_order'].assert_not_called()
        self.assertEqual(self.api['_stonks_read']()['managed_positions']['AAPL']['status'],'ERROR')

    def test_worker_zero_size_limit_blocks_entry(self):
        self.state['max_trade_eur']=0
        self.configure_worker()
        self.api['_stonks_engine_cycle']('test-owner')
        self.assertEqual(self.posts,[])

    def test_worker_daily_limit_blocks_entry(self):
        self.account['last_equity']='10020'
        self.configure_worker()
        self.api['_stonks_engine_cycle']('test-owner')
        self.assertEqual(self.posts,[])

    def test_engine_owner_transfer_only_without_outstanding_exposure(self):
        self.state['autonomous_engine']=False;self.save(self.state)
        self.api['_stonks_engine_owner_write']('test-owner')
        with self.api['app'].test_request_context('/',method='POST',json={'enabled':True}):
            session['zar_user_id']='new-owner'
            other=self.api['_stonks_default']();other['revoked']=False
            self.api['_stonks_write'](other)
            result=self.api['stonks_engine_api']()
            self.assertEqual(result.get_json()['engine_owner'],'new-owner')

    def test_engine_owner_transfer_blocked_for_open_ledger(self):
        self.entry();self.state['autonomous_engine']=False;self.save(self.state)
        self.api['_stonks_engine_owner_write']('test-owner')
        with self.api['app'].test_request_context('/',method='POST',json={'enabled':True}):
            session['zar_user_id']='new-owner'
            result=self.api['stonks_engine_api']()
            self.assertEqual(result[1],409)
            self.assertEqual(self.api['_stonks_engine_owner_read'](),'test-owner')

    def test_zero_daily_budget_blocks_entry(self):
        self.state['max_daily_loss_eur']=0
        self.configure_worker()
        self.api['_stonks_engine_cycle']('test-owner')
        self.assertEqual(self.posts,[])

    def test_manual_order_zero_position_limit_is_not_unlimited(self):
        self.state['max_position_pct']=0
        self.configure_worker()
        with self.api['app'].test_request_context('/',method='POST',json={'symbol':'AAPL','side':'buy','qty':1,'type':'limit','limit_price':100,'time_in_force':'day'}):
            session['zar_user_id']='test-owner'
            response=self.api['stonks_alpaca_order_api']()
            self.assertEqual(response[1],409)
            self.api['requests'].post.assert_not_called()


if __name__=='__main__':unittest.main()
