from app import stonks_stream
from unittest.mock import Mock, patch
from datetime import datetime, timezone
import json
import threading
from types import SimpleNamespace


def manager(**watch):
    m=stonks_stream.MarketStreamManager()
    m._ensure_threads=Mock()
    m.configure(**(watch or {'equities':['AAPL'],'crypto':['BTC/USD']}))
    return m

def test_stream_ingest_equity_trade_quote_bar_zero_token_cache():
    m = manager()
    m._ingest('equities', {'T':'t','S':'AAPL','p':250.12,'s':3,'t':'2026-10-01T12:00:00Z'})
    m._ingest('equities', {'T':'q','S':'AAPL','bp':250.10,'ap':250.14,'t':'2026-10-01T12:00:01Z'})
    m._ingest('equities', {'T':'b','S':'AAPL','o':249,'h':251,'l':248.5,'c':250.2,'v':1234,'t':'2026-10-01T12:00:00Z'})
    s = m.status()
    assert s['zero_tokens'] is True
    assert s['order_authority'] is False
    row = next(x for x in s['latest'] if x['symbol']=='AAPL')
    assert row['price'] == 250.12
    assert row['bid'] == 250.10
    assert row['ask'] == 250.14
    assert row['bar_close'] == 250.2


def test_stream_ingest_crypto_quote_midpoint():
    m = manager()
    m._ingest('crypto', {'T':'q','S':'BTC/USD','bp':65000,'ap':65010,'t':'2026-10-01T12:00:01Z'})
    row = m.status()['latest'][0]
    assert row['kind'] == 'crypto'
    assert row['mid'] == 65005


def test_symbol_normalizers_cover_equities_crypto_options():
    assert stonks_stream._norm_equity('spy') == 'SPY'
    assert stonks_stream._norm_crypto('btc-usd') == 'BTC/USD'
    assert stonks_stream._norm_crypto('ETHUSD') == 'ETH/USD'
    assert stonks_stream._norm_option('AAPL261218C00200000') == 'AAPL261218C00200000'
    assert stonks_stream._norm_equity('BTC/USD') is None


def test_stream_bounds_cache_to_current_subscriptions():
    m=manager(equities=[f'S{i}' for i in range(100)])
    assert len(m.status()['watchlist']['equities'])<=30
    for i in range(100):
        m._ingest('equities',{'T':'t','S':f'S{i}','p':10,'t':'2026-10-01T12:00:00Z'})
    assert len(m._latest)<=30
    m.configure(equities=['AAPL'])
    assert not m._latest


def test_out_of_order_ticks_do_not_replace_fresher_data_and_stale_is_visible():
    m=manager()
    m._ingest('equities',{'T':'t','S':'AAPL','p':100,'t':'2026-01-01T12:00:02Z'})
    m._ingest('equities',{'T':'t','S':'AAPL','p':999,'t':'2026-01-01T12:00:01Z'})
    row=m.status()['latest'][0]
    assert row['price']==100 and row['stale']
    m._status['equities']['authenticated']=True
    m._ingest('equities',{'T':'q','S':'AAPL','bp':101,'ap':103,'t':datetime.now(timezone.utc).isoformat()})
    row=m.status()['latest'][0]
    assert row['price']==102 and not row['stale']


def test_configure_closes_socket_without_holding_state_lock():
    m=manager(); acquired=[]
    def close():
        def callback():
            with m._lock: acquired.append(True)
        t=threading.Thread(target=callback);t.start();t.join(1)
        assert acquired, 'close callback blocked by configure lock'
    m._ws['equities']=SimpleNamespace(close=close)
    m.configure(equities=['MSFT'])
    assert acquired


def test_connection_uses_capped_exponential_backoff_and_stops_when_disabled():
    m=manager(equities=['AAPL']); delays=[]
    m._credentials=lambda: ('mock-key','mock-secret')
    m._run_json_once=Mock(side_effect=RuntimeError('offline'))
    class Wake:
        def clear(self): pass
        def wait(self, delay):
            delays.append(delay)
            if len(delays)==7: m._watch['equities']=[]
            return False
    m._restart['equities']=Wake()
    m._run_loop('equities')
    assert delays==[2.5,5,10,20,40,60,60]
    assert 'equities' not in m._threads
    assert not m.status()['feeds']['equities']['connected']


def test_old_watchlist_cannot_subscribe_after_connect_race():
    m=manager(equities=['AAPL']); sent=[]
    m._restart['equities'].clear()
    class Socket:
        def __init__(self,url,**callbacks): self.callbacks=callbacks
        def close(self): pass
        def send(self,payload): sent.append(json.loads(payload))
        def run_forever(self,**kw):
            m.configure(equities=['MSFT'])
            self.callbacks['on_open'](self)
            self.callbacks['on_message'](self,json.dumps([{'T':'success','msg':'authenticated'}]))
    with patch.dict('sys.modules',{'websocket':SimpleNamespace(WebSocketApp=Socket)}):
        m._run_json_once('equities',['AAPL'],'mock-key','mock-secret')
    assert sent==[]


def test_broker_subscription_error_closes_connection_for_backoff():
    m=manager(equities=['AAPL']); closed=[]
    m._restart['equities'].clear()
    class Socket:
        def __init__(self,url,**callbacks): self.callbacks=callbacks
        def close(self): closed.append(True)
        def send(self,payload): pass
        def run_forever(self,**kw):
            self.callbacks['on_message'](self,json.dumps([{'T':'error','code':405,'msg':'symbol limit exceeded'}]))
    with patch.dict('sys.modules',{'websocket':SimpleNamespace(WebSocketApp=Socket)}):
        m._run_json_once('equities',['AAPL'],'mock-key','mock-secret')
    assert closed and '405' in m.status()['feeds']['equities']['last_error']


def test_invalid_quote_is_rejected_and_marks_row_unusable_until_valid_quote():
    m=manager(equities=['MSFT'])
    m._status['equities']['authenticated']=True
    now=datetime.now(timezone.utc).isoformat()
    m._ingest('equities',{'T':'t','S':'MSFT','p':518.50,'t':now})
    m._ingest('equities',{'T':'q','S':'MSFT','bp':518.68,'ap':0,'t':now})
    row=m.status()['latest'][0]
    assert row['price']==518.50
    assert row['bid'] is None and row['ask'] is None
    assert row['invalid'] is True
    assert row['market_usable'] is False
    assert 'no positivos' in row['quote_invalid_reason']

    later=datetime.now(timezone.utc).isoformat()
    m._ingest('equities',{'T':'q','S':'MSFT','bp':518.60,'ap':518.80,'t':later})
    row=m.status()['latest'][0]
    assert row['bid']==518.60 and row['ask']==518.80
    assert row['invalid'] is False
    assert row['market_usable'] is True


def test_crossed_and_absurd_spread_quotes_are_rejected():
    m=manager(equities=['AAPL'])
    m._status['equities']['authenticated']=True
    now=datetime.now(timezone.utc).isoformat()
    m._ingest('equities',{'T':'t','S':'AAPL','p':250,'t':now})
    m._ingest('equities',{'T':'q','S':'AAPL','bp':251,'ap':250,'t':now})
    row=m.status()['latest'][0]
    assert row['invalid'] and 'bid > ask' in row['quote_invalid_reason']
    m._ingest('equities',{'T':'q','S':'AAPL','bp':100,'ap':200,'t':datetime.now(timezone.utc).isoformat()})
    row=m.status()['latest'][0]
    assert row['invalid'] and 'spread anómalo' in row['quote_invalid_reason']
