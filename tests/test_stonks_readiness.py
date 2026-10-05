import ast
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock
import pytest
from app import stonks_execution as execution, stonks_learning as learning, stonks_readiness as readiness, stonks_stream
from test_stonks_learning import closed_record
from test_stonks_multiprocess import load_stream_plan
from test_stonks_lifecycle import control_plane


def safe_state():
    return dict(mode='paper', execution_mode='paper_auto', paused=False, revoked=False,
                max_trade_eur=25, max_daily_loss_eur=10, max_position_pct=20)


@pytest.mark.parametrize('flags', [dict(mode='live'), dict(execution_mode='shadow'), dict(paused=True), dict(revoked=True), dict(max_trade_eur=float('nan'))])
def test_final_transport_guard_never_posts(flags):
    post=Mock(); state=safe_state();state.update(flags)
    with pytest.raises(RuntimeError):
        execution.PaperExecutionAdapter(post).submit({},state,('fixture-key','fixture-secret'))
    post.assert_not_called()


def test_live_unavailable_even_with_environment(monkeypatch):
    monkeypatch.setenv('LIVE_TRADING_ENABLED','true')
    with pytest.raises(RuntimeError, match='LIVE BLOQUEADO'): execution.LiveExecutionAdapter()
    assert execution.LIVE_TRADING_ENABLED is False
    post=Mock()
    with pytest.raises(RuntimeError): execution.PaperExecutionAdapter(post).submit({'mode':'live'},safe_state(),('x','y'))
    post.assert_not_called()


def test_readiness_is_read_only_and_missing_evidence_pending():
    state=safe_state();state.update(paper_connected=True,paper_learning_journal_count=25,
        paper_learning={'overall':{'trades':25}},engine_last_reconcile='2000-01-01T00:00:00Z')
    before=deepcopy(state)
    result=readiness.evaluate(state,{}, {'ok':True})
    assert state==before
    assert result['status']=='bloqueado' and not result['live_trading_enabled']
    assert result['orders_created']==result['token_cost']==0
    rows={r['name']:r for r in result['checks']}
    assert rows['Broker connection']['status']=='bloqueado'
    assert rows['Journal persistence']['status']=='pendiente'
    assert rows['Estrategia validada']['status']=='pendiente'
    assert rows['Paper sample size']['status']=='preparado tecnicamente'


def test_learning_history_not_truncated_or_reingested(monkeypatch):
    monkeypatch.setattr(learning,'MAX_TRADES',2)
    state=safe_state();state.update(stop_loss_pct=1,take_profit_pct=2,
        position_ledger={str(i):closed_record(str(i)) for i in range(4)})
    controls={k:deepcopy(v) for k,v in state.items() if k!='position_ledger'}
    assert len(learning.ingest(state)['added'])==4
    assert len(state['paper_learning_journal'])==4
    assert len(learning.ingest(state)['added'])==0
    assert state['paper_learning']['overall']['trades']==2
    assert {k:state[k] for k in controls}==controls


@pytest.mark.parametrize('flags', [dict(baseline_flat=False),dict(ownership_conflict=True),dict(purpose='TEST_LIFECYCLE')])
def test_learning_rejects_unowned_or_test(flags):
    row=closed_record();row.update(flags)
    assert learning.ingest({'position_ledger':{'x':row}})['added']==[]


def test_learning_rejects_invalid_prices_and_reports_actual_streak():
    row=closed_record();row['entry_fill']['price']=float('nan')
    assert learning.ingest({'position_ledger':{'x':row}})['added']==[]
    state={'position_ledger':{str(i):closed_record(str(i),pnl=p) for i,p in enumerate([1,-1,-2])}}
    result=learning.ingest(state)['summary']['overall']
    assert result['current_streak']==-2 and result['recent_pnl_usd']==-2


def test_stream_snapshot_expires_without_mutating_persistence():
    old=(datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat()
    snap={'feeds':{'equities':dict(connected=True,authenticated=True,last_message_at=old)},
          'latest':[dict(symbol='AAPL',kind='equities',timestamp=old,stale=False)]}
    copy=deepcopy(snap);out=stonks_stream.refresh_snapshot(snap)
    assert snap==copy and out['latest'][0]['stale'] and not out['feeds']['equities']['connected']


def test_nonowner_cannot_force_activation_and_positions_take_priority():
    import os
    ns=load_stream_plan();state={'engine_symbols':['AAPL'],'engine_last_positions':[{'symbol':'MSFT'}],
        'engine_last_open_orders':[{'symbol':'SPY'}], 'stream_watchlist_equities':['QQQ']}
    ns['_stonks_stream_plan'](state,activate=True)
    assert not ns['stonks_stream'].MANAGER.configures
    ns['_STONKS_ENGINE_OWNER_PID']=os.getpid()
    ns['_stonks_stream_plan'](state,activate=True)
    assert ns['stonks_stream'].MANAGER.configures[0]['equities']==['MSFT','SPY','AAPL','QQQ']


@pytest.mark.parametrize('timeframe', ['1Min','5Min','15Min'])
def test_signal_uses_only_fully_closed_bars(tmp_path,timeframe):
    ns=control_plane(tmp_path);now=datetime.now(timezone.utc)
    minutes=int(timeframe[:-3])
    rows=[{'t':(now-timedelta(minutes=minutes+1)).isoformat(),'o':100,'h':101,'l':99,'c':100},
          {'t':(now-timedelta(seconds=30)).isoformat(),'o':100,'h':102,'l':99,'c':101}]
    ns['_alpaca_paper_request']=Mock(return_value={'is_open':True})
    ns['_alpaca_market_request']=Mock(return_value={'bars':{'AAPL':rows}})
    signal,_=ns['_stonks_current_signal']('AAPL',timeframe=timeframe)
    assert signal['bars']==1 and signal['bar_time']==rows[0]['t']


def test_all_broker_order_posts_use_guarded_adapter():
    root=Path(__file__).resolve().parents[1]
    main=(root/'app/main.py').read_text(encoding='utf-8')
    assert 'paper-api.alpaca.markets/v2/orders' not in main
    adapter=(root/'app/stonks_execution.py').read_text()
    assert adapter.count('https://paper-api.alpaca.markets/v2/orders')==1


@pytest.mark.parametrize('endpoint', ['stonks_orphan_test_close_api', 'stonks_close_single_paper_position_api'])
@pytest.mark.parametrize('flags', [{}, {'paused':True}, {'revoked':True}, {'mode':'live'},
                                 {'execution_mode':'shadow'}, {'max_trade_eur':0},
                                 {'max_daily_loss_eur':0}, {'max_position_pct':'NaN'}])
def test_recovery_closes_use_final_paper_guard(tmp_path, endpoint, flags):
    ns=control_plane(tmp_path)
    state=ns['_stonks_default']();state.update(safe_state());state.update(flags)
    position={'symbol':'AAPL','qty':'0.1'}
    ns['_alpaca_paper_credentials']=lambda:('fixture-key','fixture-secret')
    ns['_alpaca_paper_request']=Mock(side_effect=lambda path, **kw:
        [position] if path=='/v2/positions' else [] if path=='/v2/orders' else
        {'status':'ACTIVE','trading_blocked':False,'account_blocked':False})
    ns['_stonks_orphan_test_snapshot']=Mock(return_value={
        'available':True,'symbol':'AAPL','qty':'0.1','owner':'previous'})
    response=ns['requests'].post.return_value
    response.ok=True;response.json.return_value={'id':'fixture-order','status':'new'}
    with ns['app'].test_request_context('/',method='POST',json={'confirm':True}):
        ns['session']['zar_user_id']='test-owner'
        ns['_stonks_write'](state)
        result,status=ns[endpoint]()
    if flags:
        assert status==502 and result.get_json()['ok'] is False
        ns['requests'].post.assert_not_called()
    else:
        assert status==202 and result.get_json()['paper'] is True
        ns['requests'].post.assert_called_once()
        args,kwargs=ns['requests'].post.call_args
        assert args[0]=='https://paper-api.alpaca.markets/v2/orders'
        assert kwargs['json']['symbol']=='AAPL'
        assert kwargs['json']['qty']=='0.1'
        assert kwargs['json']['side']=='sell'


@pytest.mark.parametrize('endpoint', ['stonks_orphan_test_close_api', 'stonks_close_single_paper_position_api'])
def test_recovery_close_requires_confirmation_before_broker_reads(tmp_path, endpoint):
    ns=control_plane(tmp_path)
    ns['_alpaca_paper_request']=Mock(side_effect=AssertionError('must not read broker'))
    ns['_stonks_orphan_test_snapshot']=Mock(side_effect=AssertionError('must not inspect'))
    with ns['app'].test_request_context('/',method='POST',json={}):
        _,status=ns[endpoint]()
    assert status==400
    ns['requests'].post.assert_not_called()


def test_nonowner_process_cannot_inherit_stream_authority(tmp_path):
    import os, subprocess, sys
    code = "from test_stonks_multiprocess import load_stream_plan; import os; ns=load_stream_plan(); ns['_STONKS_ENGINE_OWNER_PID']="+str(os.getpid())+"; ns['_stonks_stream_plan']({},activate=True); assert not ns['stonks_stream'].MANAGER.configures"
    env=dict(os.environ);env['PYTHONPATH']=str(Path(__file__).resolve().parent)+os.pathsep+env.get('PYTHONPATH','')
    result=subprocess.run([sys.executable,'-c',code],env=env,capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr


def test_priority_options_and_crypto_are_not_misclassified():
    import os
    ns=load_stream_plan();ns['_STONKS_ENGINE_OWNER_PID']=os.getpid()
    ns['_stonks_stream_plan']({'engine_last_positions':[{'symbol':'BTC/USD','asset_class':'crypto'},
        {'symbol':'AAPL261016C00200000','asset_class':'us_option'}],'engine_symbols':['AAPL']})
    plan=ns['stonks_stream'].MANAGER.configures[0]
    assert plan=={'equities':['AAPL'],'crypto':['BTC/USD'],'options':['AAPL261016C00200000']}


@pytest.mark.parametrize('endpoint',['stonks_controls_api','stonks_decision_api','stonks_alpaca_order_api'])
def test_frontend_cannot_request_live(tmp_path,endpoint):
    ns=control_plane(tmp_path)
    with ns['app'].test_request_context('/',method='POST',json={'mode':'live'}):
        response,status=ns[endpoint]()
        assert status==409 and response.get_json()['error']=='LIVE BLOQUEADO'
    ns['requests'].post.assert_not_called()


# Exercise the production cycle directly: no browser exists in these tests.
import unittest
import test_stonks_lifecycle as baseline
class WorkerReadinessTests(unittest.TestCase):
    setUp=baseline.LifecycleTests.setUp
    configure_worker=baseline.LifecycleTests.configure_worker

    def test_closed_hold_paused_revoked_and_risk_never_send(self):
        for flags, signal, market in [({},'BUY',False),({},'HOLD',True),({'paused':True},'BUY',True),
            ({'revoked':True},'BUY',True),({'max_trade_eur':0},'BUY',True),({'execution_mode':'shadow'},'BUY',True)]:
            with self.subTest(flags=flags,signal=signal,market=market):
                self.state.update(paused=False,revoked=False,max_trade_eur=1000,execution_mode='paper_auto')
                self.state.update(flags);self.clock['is_open']=market;self.configure_worker(signal)
                self.api['_stonks_engine_cycle']('test-owner')
                assert self.posts==[]

    def test_stale_or_blocked_account_never_sends(self):
        self.configure_worker()
        self.api['_alpaca_market_request'].return_value={'trade':{'p':100,'t':'2000-01-01T00:00:00Z'}}
        self.api['_stonks_engine_cycle']('test-owner')
        assert self.posts==[]
        self.account['trading_blocked']=True;self.configure_worker()
        self.api['_stonks_engine_cycle']('test-owner')
        assert self.posts==[]
