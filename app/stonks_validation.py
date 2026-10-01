"""Deterministic technical readiness checks for ZAR Stonks Shadow mode.

The gate is descriptive and configurable. It does not rank instruments, make
investment recommendations, send broker orders or enable Paper automatically.
"""
from statistics import median

DEFAULT_CRITERIA = {
    'min_periods': 3,
    'min_positive_period_pct': 50.0,
    'max_abs_drawdown_pct': 10.0,
    'min_wf_positive_pct': 50.0,
    'min_wf_median_sharpe': 0.20,
    'min_wf_trades': 6,
}


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def assess_symbol(symbol, period_rows, walk_row=None, criteria=None):
    c = dict(DEFAULT_CRITERIA)
    if criteria:
        c.update(criteria)
    rows = [r for r in period_rows if r.get('ok', True) and str(r.get('symbol','')).upper() == str(symbol).upper()]
    returns = [_num(r.get('return_pct')) for r in rows]
    positive = sum(1 for x in returns if x > 0)
    positive_pct = (positive / len(rows) * 100.0) if rows else 0.0
    drawdowns = [abs(_num(r.get('max_drawdown_pct'))) for r in rows]
    max_abs_dd = max(drawdowns) if drawdowns else 0.0
    period_sharpes = [_num(r.get('sharpe')) for r in rows if r.get('sharpe') is not None]

    wf = (walk_row or {}).get('summary') or {}
    wf_positive_pct = _num(wf.get('positive_fold_pct'))
    wf_sharpe = wf.get('median_sharpe')
    wf_sharpe_num = _num(wf_sharpe, -999.0) if wf_sharpe is not None else -999.0
    wf_trades = int(wf.get('trades') or 0)

    checks = [
        {'code':'PERIODS','label':'Periodos válidos','value':len(rows),'required':f">={int(c['min_periods'])}", 'passed':len(rows) >= int(c['min_periods'])},
        {'code':'POSITIVE_PERIODS','label':'Periodos positivos','value':round(positive_pct,1),'required':f">={c['min_positive_period_pct']:.0f}%", 'passed':positive_pct >= c['min_positive_period_pct']},
        {'code':'DRAWDOWN','label':'Drawdown absoluto máx.','value':round(max_abs_dd,2),'required':f"<={c['max_abs_drawdown_pct']:.1f}%", 'passed':max_abs_dd <= c['max_abs_drawdown_pct']},
        {'code':'WF_POSITIVE','label':'Ventanas OOS positivas','value':round(wf_positive_pct,1),'required':f">={c['min_wf_positive_pct']:.0f}%", 'passed':wf_positive_pct >= c['min_wf_positive_pct']},
        {'code':'WF_SHARPE','label':'Sharpe mediano OOS','value':None if wf_sharpe is None else round(wf_sharpe_num,3),'required':f">={c['min_wf_median_sharpe']:.2f}", 'passed':wf_sharpe is not None and wf_sharpe_num >= c['min_wf_median_sharpe']},
        {'code':'WF_TRADES','label':'Operaciones OOS','value':wf_trades,'required':f">={int(c['min_wf_trades'])}", 'passed':wf_trades >= int(c['min_wf_trades'])},
    ]
    passed = all(x['passed'] for x in checks)
    return {
        'symbol': str(symbol).upper(),
        'status': 'MEETS_SHADOW_CRITERIA' if passed else 'MORE_EVIDENCE_REQUIRED',
        'meets_shadow_criteria': passed,
        'periods': len(rows),
        'positive_period_pct': round(positive_pct,1),
        'max_abs_drawdown_pct': round(max_abs_dd,2),
        'median_period_sharpe': round(median(period_sharpes),3) if period_sharpes else None,
        'wf_positive_pct': round(wf_positive_pct,1),
        'wf_median_sharpe': None if wf_sharpe is None else round(wf_sharpe_num,3),
        'wf_trades': wf_trades,
        'checks': checks,
        'note': 'Criterios técnicos para Shadow; no es una recomendación ni habilita Paper automáticamente.'
    }


def assess_suite(rows, walk_forward, criteria=None):
    walk_map = {str(x.get('symbol','')).upper(): x for x in (walk_forward or [])}
    symbols=[]
    for r in rows or []:
        s=str(r.get('symbol','')).upper()
        if s and s not in symbols: symbols.append(s)
    results=[assess_symbol(s, rows or [], walk_map.get(s), criteria) for s in symbols]
    return {
        'criteria': dict(DEFAULT_CRITERIA if criteria is None else {**DEFAULT_CRITERIA, **criteria}),
        'symbols': results,
        'model': {'deterministic': True, 'llm_tokens': 0, 'broker_orders': False, 'auto_enable_paper': False}
    }
