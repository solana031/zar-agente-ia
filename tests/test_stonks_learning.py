from app import stonks_learning


def closed_record(cid='zar-e-1', pnl=5.0, ret=2.5, regime='trend'):
    return {
        'client_order_id': cid, 'closed': True, 'symbol': 'AAPL', 'side': 'buy',
        'strategy': 'trend', 'timeframe': '1Min', 'submitted_at': '2026-10-01T13:30:00+00:00',
        'entry_fill': {'qty':'2','price':100.0,'filled_at':'2026-10-01T13:30:00+00:00'},
        'decision_context': {
            'signal':'BUY','bar_time':'2026-10-01T13:29:00+00:00','regime':regime,
            'indicators':{'sma20':101,'sma50':99,'atr_pct':1.2,'regime':regime},
            'sentiment':'neutral','sentiment_score':0,'risk_decision':'APROBADA',
            'risk_reason':'Risk OK','asset_class':'us_equity','news_sources':[]
        },
        'mfe_pct':3.0, 'mae_pct':-0.8,
        'learning_result': {
            'complete': True, 'qty':'2', 'exit_price':102.5,
            'realized_pnl':pnl, 'return_pct':ret, 'duration_s':3600,
            'closed_at':'2026-10-01T14:30:00+00:00','exit_reason':'TP'
        }
    }


def test_learning_ingest_is_idempotent_and_paper_only():
    state={'position_ledger':{'zar-e-1':closed_record()},'paper_learning_journal':[]}
    first=stonks_learning.ingest(state)
    second=stonks_learning.ingest(state)
    assert len(first['added'])==1
    assert len(second['added'])==0
    assert len(state['paper_learning_journal'])==1
    row=state['paper_learning_journal'][0]
    assert row['paper'] is True and row['order_created'] is True
    assert state['paper_learning']['risk_authority'] is False
    assert state['paper_learning']['live_authority'] is False


def test_learning_needs_minimum_sample_before_priority_can_influence():
    state={'position_ledger':{},'paper_learning_journal':[]}
    for i in range(19):
        state['position_ledger'][f'c{i}']=closed_record(f'c{i}',pnl=1.0,ret=0.5)
    stonks_learning.ingest(state)
    g=state['paper_learning']['groups'][0]
    assert g['trades']==19
    assert g['can_influence_priority'] is False
    assert g['priority_score']==0.0
    state['position_ledger']['c19']=closed_record('c19',pnl=1.0,ret=0.5)
    stonks_learning.ingest(state)
    g=state['paper_learning']['groups'][0]
    assert g['trades']==20
    assert g['can_influence_priority'] is True
    assert g['priority_score']>0


def test_test_lifecycle_and_incomplete_records_are_ignored():
    a=closed_record('test');a['purpose']='TEST_LIFECYCLE'
    b=closed_record('incomplete');b['learning_result']['complete']=False
    state={'position_ledger':{'test':a,'incomplete':b},'paper_learning_journal':[]}
    out=stonks_learning.ingest(state)
    assert out['added']==[]
    assert state['paper_learning']['overall']['trades']==0


def test_decision_context_is_bounded_and_does_not_carry_order_authority():
    signal={'signal':'BUY','bar_time':'t','indicators':{'sma20':1,'sma50':2,'secret':'drop','regime':'trend'}}
    news={'sentiment':'bullish','sentiment_score':25,'items':[{'title':'x'*500,'url':'https://example.com','score':18,'sentiment':'bullish'}]*20}
    ctx=stonks_learning.decision_context(signal,news)
    assert 'secret' not in ctx['indicators']
    assert len(ctx['news_sources'])<=5
    assert len(ctx['news_sources'][0]['title'])<=180
    assert 'risk_authority' not in ctx
