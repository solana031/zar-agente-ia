import inspect
from unittest.mock import Mock
import pytest

from app import stonks_execution, stonks_live_readonly, stonks_readiness


class Resp:
    def __init__(self, data, ok=True, status_code=200):
        self._data=data
        self.ok=ok
        self.status_code=status_code
    def json(self):
        return self._data


def test_live_adapter_exposes_no_write_methods():
    forbidden={'submit','buy','sell','cancel','cancel_order','replace','replace_order','modify','patch','post','delete'}
    assert not any(hasattr(stonks_live_readonly.LiveReadOnlyAdapter, x) for x in forbidden)


@pytest.mark.parametrize('action',['buy','sell','cancel','replace','direct'])
def test_live_safety_gate_denies_every_write(action):
    assert stonks_execution.LIVE_TRADING_ENABLED is False
    assert stonks_execution.LiveSafetyGate.allowed(action) is False
    with pytest.raises(RuntimeError, match='LIVE BLOQUEADO'):
        stonks_execution.LiveSafetyGate.require(action)


def test_live_readonly_uses_only_get_and_sanitizes_snapshot():
    calls=[]
    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append((url, headers, params, timeout))
        if url.endswith('/account'):
            return Resp({'equity':'10000.12','cash':'4000','buying_power':'8000','portfolio_value':'10000.12'})
        if url.endswith('/positions'):
            return Resp([{'symbol':'AAPL','asset_class':'us_equity','qty':'2','market_value':'400','unrealized_pl':'12','unrealized_plpc':'0.03'}])
        if url.endswith('/orders'):
            return Resp([{'id':'o1','symbol':'AAPL','side':'buy','type':'limit','status':'new','qty':'1'}])
        if url.endswith('/clock'):
            return Resp({'is_open':True,'next_open':'n','next_close':'c'})
        raise AssertionError(url)
    adapter=stonks_live_readonly.LiveReadOnlyAdapter(get=fake_get)
    snap=adapter.snapshot(('live-key','live-secret'))
    assert snap['connected'] and snap['read_only'] and not snap['live_trading_enabled']
    assert snap['equity']==10000.12 and snap['exposure']==400.0
    assert snap['orders_created']==0 and snap['token_cost']==0
    assert len(calls)==4 and all(c[0].startswith('https://api.alpaca.markets/v2/') for c in calls)
    assert all(c[1]['APCA-API-KEY-ID']=='live-key' for c in calls)


def test_missing_credentials_never_calls_network(monkeypatch):
    monkeypatch.delenv('ALPACA_LIVE_READONLY_KEY', raising=False)
    monkeypatch.delenv('ALPACA_LIVE_READONLY_SECRET', raising=False)
    stonks_live_readonly.reset_cache()
    get=Mock()
    result=stonks_live_readonly.status(adapter=stonks_live_readonly.LiveReadOnlyAdapter(get=get))
    assert result['state']=='not_connected'
    assert result['orders_created']==0
    get.assert_not_called()


def test_status_cache_limits_broker_reads(monkeypatch):
    monkeypatch.setenv('ALPACA_LIVE_READONLY_KEY','x')
    monkeypatch.setenv('ALPACA_LIVE_READONLY_SECRET','y')
    stonks_live_readonly.reset_cache()
    adapter=Mock()
    adapter.snapshot.return_value={'state':'read_only','connected':True,'configured':True,'read_only':True,
        'live_trading_enabled':False,'label':'LIVE TRADING BLOQUEADO','positions':[],'open_orders':[],
        'positions_count':0,'open_orders_count':0,'orders_created':0,'token_cost':0,'updated_at':'x'}
    a=stonks_live_readonly.status(adapter=adapter,ttl_seconds=60)
    b=stonks_live_readonly.status(adapter=adapter,ttl_seconds=60)
    assert a==b
    assert adapter.snapshot.call_count==1


def test_readiness_includes_live_account_without_live_authority(monkeypatch):
    monkeypatch.setattr(stonks_readiness.stonks_live_readonly,'status',lambda:{
        'state':'read_only','connected':True,'configured':True,'read_only':True,
        'live_trading_enabled':False,'label':'LIVE TRADING BLOQUEADO','equity':1000.0,'cash':500.0,
        'positions_count':1,'positions':[],'open_orders':[],'orders_created':0,'token_cost':0})
    result=stonks_readiness.evaluate({'mode':'paper','max_trade_eur':25,'max_daily_loss_eur':10,'max_position_pct':20,
        'paused':False,'revoked':False}, {}, {'ok':True})
    rows={r['name']:r for r in result['checks']}
    assert rows['Cuenta real read-only']['status']=='preparado tecnicamente'
    assert result['live_account']['equity']==1000.0
    assert result['live_trading_enabled'] is False and result['orders_created']==0
