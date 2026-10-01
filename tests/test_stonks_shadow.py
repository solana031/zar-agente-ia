from datetime import datetime, timedelta, timezone
from app import stonks_shadow


def bars(start, closes):
    rows=[]
    for i,c in enumerate(closes, start=1):
        t=start+timedelta(minutes=i)
        rows.append({'t':t.isoformat(),'o':c,'h':c+1,'l':c-1,'c':c})
    return rows


def test_buy_horizons_and_mfe_mae():
    start=datetime(2026,1,1,14,30,tzinfo=timezone.utc)
    ev={'timestamp':start.isoformat(),'symbol':'AAA','signal':'BUY','price':100,'decision':'APROBADA','estimated_value':20}
    row=stonks_shadow.update_event(ev,bars(start,[101+i*0.1 for i in range(60)]),now=start+timedelta(hours=2))
    assert row['outcome_status']=='complete'
    assert row['outcomes']['5']['return_pct']>0
    assert row['outcomes']['60']['hypothetical_pnl_usd']>0
    assert row['mfe_pct']>0
    assert row['mae_pct']<=0


def test_sell_return_is_direction_adjusted():
    start=datetime(2026,1,1,14,30,tzinfo=timezone.utc)
    ev={'timestamp':start.isoformat(),'symbol':'AAA','signal':'SELL','price':100,'decision':'DENEGADA','estimated_value':20}
    row=stonks_shadow.update_event(ev,bars(start,[99-i*0.1 for i in range(60)]))
    assert row['outcomes']['5']['return_pct']>0
    assert row['outcomes']['60']['hypothetical_pnl_usd'] is None


def test_partial_until_enough_market_bars():
    start=datetime(2026,1,1,14,30,tzinfo=timezone.utc)
    ev={'timestamp':start.isoformat(),'symbol':'AAA','signal':'BUY','price':100}
    row=stonks_shadow.update_event(ev,bars(start,[101]*16))
    assert '5' in row['outcomes'] and '15' in row['outcomes']
    assert '60' not in row['outcomes']
    assert row['outcome_status']=='partial'


def test_summary_never_reports_orders():
    start=datetime(2026,1,1,14,30,tzinfo=timezone.utc)
    ev={'timestamp':start.isoformat(),'symbol':'AAA','signal':'BUY','price':100,'decision':'APROBADA','estimated_value':10}
    row=stonks_shadow.update_event(ev,bars(start,[101]*60))
    s=stonks_shadow.summarize([row])
    assert s['orders_created']==0
    assert s['horizons']['60']['evaluated']==1
    assert s['horizons']['60']['approved_hypothetical_pnl_usd']>0


def test_outcome_excludes_open_future_duplicate_and_pre_signal_bars():
    start=datetime(2026,1,1,14,30,tzinfo=timezone.utc)
    ev={'timestamp':start.isoformat(),'symbol':'AAA','signal':'BUY','price':100}
    data=bars(start,[101]*60)
    # Only four distinct bars have fully closed at 14:35:30.
    mixed=data+[data[0]]*10+[{'t':start.isoformat(),'h':999,'l':1,'c':999}]
    now=start+timedelta(minutes=5,seconds=30)
    out=stonks_shadow.update_event(ev,mixed,now=now)
    assert out['outcomes']=={} and out['outcome_bars']==4
    assert out['mfe_pct']==2
    out=stonks_shadow.update_event(ev,mixed,now=start+timedelta(minutes=6))
    assert out['outcomes']['5']['return_pct']==1
    assert out['outcome_bars']==5
