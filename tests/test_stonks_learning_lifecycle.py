from app import stonks_lifecycle, stonks_learning


def test_closed_reconciled_paper_trade_produces_learning_result():
    state={
        'revoked':False,'paused':False,'mode':'paper','execution_mode':'paper_auto',
        'autonomous_engine':True,'position_lifecycle_enabled':True,
        'stop_loss_pct':1.0,'take_profit_pct':2.0,
        'max_trade_eur':1000,'max_daily_loss_eur':100,'max_position_pct':100,
        'position_ledger':{},'managed_positions':{},'pending_entries':{},
        'paper_learning_journal':[]
    }
    rec=stonks_lifecycle.entry_intent(state,'AAPL','buy','2','trend','1Min')
    rec['decision_context']=stonks_learning.decision_context(
        {'signal':'BUY','bar_time':'2026-10-01T13:29:00+00:00','indicators':{'regime':'trend','atr_pct':1.0}},
        {'sentiment':'neutral','items':[]})
    exit_cid='zar-x-test'
    rec['trigger']='TP'
    rec['exits']=[{'client_order_id':exit_cid,'qty':'2','trigger':'TP','submitted_at':'2026-10-01T14:00:00+00:00'}]
    entry={
        'id':'entry','client_order_id':rec['client_order_id'],'symbol':'AAPL','side':'buy',
        'qty':'2','filled_qty':'2','filled_avg_price':'100','status':'filled',
        'submitted_at':rec['submitted_at'],'updated_at':rec['submitted_at'],'filled_at':rec['submitted_at']
    }
    exit_order={
        'id':'exit','client_order_id':exit_cid,'symbol':'AAPL','side':'sell',
        'qty':'2','filled_qty':'2','filled_avg_price':'102','status':'filled',
        'submitted_at':'2026-10-01T14:00:00+00:00','updated_at':'2026-10-01T14:00:00+00:00','filled_at':'2026-10-01T14:00:00+00:00'
    }
    orders={entry['client_order_id']:entry,exit_cid:exit_order}
    stonks_lifecycle.manage(
        state, [], list(orders.values()), lambda cid:orders.get(cid),
        lambda body: (_ for _ in ()).throw(AssertionError('no new order expected')),
        lambda state:None, lambda *args,**kwargs:None,
        lambda:{'equity':'10000','last_equity':'10000'}, {'is_open':True})
    assert rec['closed'] is True
    assert rec['learning_result']['complete'] is True
    assert round(rec['learning_result']['realized_pnl'],2)==4.0
    assert round(rec['learning_result']['return_pct'],2)==2.0
    out=stonks_learning.ingest(state)
    assert len(out['added'])==1
    assert state['paper_learning']['overall']['trades']==1
