from app import stonks_stream


def test_stream_ingest_equity_trade_quote_bar_zero_token_cache():
    m = stonks_stream.MarketStreamManager()
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
    m = stonks_stream.MarketStreamManager()
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
