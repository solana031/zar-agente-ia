from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import median

HORIZONS = (5, 15, 60)
# Eight engine symbols, one observation per minute, plus completion margin.
MAX_EVENTS = 600


def _ts(value):
    if isinstance(value, datetime):
        dt=value
    else:
        dt=datetime.fromisoformat(str(value or '').replace('Z','+00:00'))
    if dt.tzinfo is None:
        dt=dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def directional_return_pct(signal, entry, exit_price):
    entry=_num(entry)
    exit_price=_num(exit_price)
    if entry <= 0 or exit_price <= 0:
        return None
    raw=(exit_price-entry)/entry*100.0
    return raw if str(signal or '').upper()=='BUY' else -raw


def _bars_after(event, bars, now):
    try:
        start=_ts(event.get('timestamp'))
    except Exception:
        return []
    clean={}
    for bar in bars or []:
        try:
            bt=_ts(bar.get('t'))
            if bt <= start or bt + timedelta(minutes=1) > now:
                continue
            if not all(k in bar for k in ('h','l','c')):
                continue
            clean[bt]=bar
        except Exception:
            continue
    return [clean[t] for t in sorted(clean)]


def update_event(event, bars, now=None):
    """Attach forward-only outcome metrics to one Shadow event.

    Horizons are measured in completed 1-minute market bars after the event,
    not wall-clock minutes. This naturally skips overnight/weekend gaps.
    """
    out=dict(event or {})
    entry=_num(out.get('price'))
    signal=str(out.get('signal') or '').upper()
    if signal not in ('BUY','SELL') or entry <= 0:
        out['outcome_status']='invalid'
        return out
    now=_ts(now or datetime.now(timezone.utc))
    after=_bars_after(out,bars,now)
    outcomes=dict(out.get('outcomes') or {})
    for horizon in HORIZONS:
        key=str(horizon)
        if key in outcomes or len(after) < horizon:
            continue
        bar=after[horizon-1]
        close=_num(bar.get('c'))
        ret=directional_return_pct(signal,entry,close)
        if ret is None:
            continue
        estimated=_num(out.get('estimated_value'))
        approved=str(out.get('decision') or '').upper().startswith('APROBADA')
        outcomes[key]={
            'bars':horizon,
            'price':round(close,6),
            'return_pct':round(ret,6),
            'bar_time':bar.get('t'),
            'hypothetical_pnl_usd':round(estimated*ret/100.0,6) if approved and estimated>0 else None,
        }
    window=after[:HORIZONS[-1]]
    if window:
        highs=[_num(b.get('h')) for b in window if _num(b.get('h'))>0]
        lows=[_num(b.get('l')) for b in window if _num(b.get('l'))>0]
        if highs and lows:
            if signal=='BUY':
                mfe=(max(highs)-entry)/entry*100.0
                mae=(min(lows)-entry)/entry*100.0
            else:
                mfe=(entry-min(lows))/entry*100.0
                mae=(entry-max(highs))/entry*100.0
            out['mfe_pct']=round(mfe,6)
            out['mae_pct']=round(mae,6)
    out['outcomes']=outcomes
    out['outcome_bars']=len(after)
    out['outcome_status']='complete' if str(HORIZONS[-1]) in outcomes else ('partial' if outcomes else 'pending')
    out['outcome_updated_at']=(now or datetime.now(timezone.utc)).isoformat()
    return out


def update_log(events, bars_by_symbol, now=None):
    rows=[]
    for event in events or []:
        symbol=str((event or {}).get('symbol') or '').upper()
        if (event or {}).get('outcome_status')=='complete':
            rows.append(dict(event))
        else:
            rows.append(update_event(event,(bars_by_symbol or {}).get(symbol,[]),now=now))
    return rows


def _horizon_stats(events, horizon):
    key=str(horizon)
    vals=[]
    pnls=[]
    for event in events or []:
        row=(event.get('outcomes') or {}).get(key)
        if not row:
            continue
        ret=_num(row.get('return_pct'))
        vals.append(ret)
        pnl=row.get('hypothetical_pnl_usd')
        if pnl is not None:
            pnls.append(_num(pnl))
    return {
        'evaluated':len(vals),
        'positive_pct':round(sum(1 for x in vals if x>0)/len(vals)*100.0,2) if vals else 0.0,
        'median_return_pct':round(median(vals),4) if vals else None,
        'avg_return_pct':round(sum(vals)/len(vals),4) if vals else None,
        'approved_hypothetical_pnl_usd':round(sum(pnls),4) if pnls else 0.0,
    }


def summarize(events):
    rows=list(events or [])
    complete=[x for x in rows if x.get('outcome_status')=='complete']
    mfe=[_num(x.get('mfe_pct')) for x in rows if x.get('mfe_pct') is not None]
    mae=[_num(x.get('mae_pct')) for x in rows if x.get('mae_pct') is not None]
    return {
        'signals':len(rows),
        'pending':sum(1 for x in rows if x.get('outcome_status') in (None,'pending','partial')),
        'complete':len(complete),
        'risk_approved':sum(1 for x in rows if str(x.get('decision') or '').upper().startswith('APROBADA')),
        'horizons':{str(h):_horizon_stats(rows,h) for h in HORIZONS},
        'avg_mfe_pct':round(sum(mfe)/len(mfe),4) if mfe else None,
        'avg_mae_pct':round(sum(mae)/len(mae),4) if mae else None,
        'orders_created':0,
    }
