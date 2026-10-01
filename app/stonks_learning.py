"""Deterministic Paper-learning journal for ZAR Stonks.

This module has no broker credentials, no order authority and no LLM calls.
It converts fully reconciled/closed ZAR Paper positions into persistent learning
records and derives descriptive performance statistics. Learning may influence
priority/ranking only after a minimum sample; it never changes Risk, permissions
or Paper/Live mode.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from statistics import mean, median
import math

MAX_TRADES = 5000
MIN_SAMPLE = 20


def _now():
    return datetime.now(timezone.utc).isoformat()


def _f(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def _max_drawdown_from_pnl(rows):
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for row in rows:
        equity += _f(row.get('realized_pnl'))
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return round(max_dd, 6)


def _loss_streak(rows):
    best = cur = 0
    for row in rows:
        if _f(row.get('realized_pnl')) < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def _confidence(n):
    if n < 5:
        return 'insuficiente'
    if n < MIN_SAMPLE:
        return 'en_desarrollo'
    return 'muestra_util'


def _priority_score(rows):
    """Descriptive priority score, not a forecast and never a Risk input."""
    n = len(rows)
    if n < MIN_SAMPLE:
        return 0.0
    pnls = [_f(x.get('realized_pnl')) for x in rows]
    rets = [_f(x.get('return_pct')) for x in rows]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x < 0]
    pf = (sum(wins) / abs(sum(losses))) if losses else (3.0 if wins else 1.0)
    expectancy_pct = mean(rets) if rets else 0.0
    win_rate = (len(wins) / n) * 100.0 if n else 0.0
    # Conservative bounded ranking only; no sizing/risk effect.
    score = expectancy_pct * 8.0 + (pf - 1.0) * 18.0 + (win_rate - 50.0) * 0.35
    return round(max(-100.0, min(100.0, score)), 2)


def _summary_for(rows):
    rows = list(rows or [])
    n = len(rows)
    if not n:
        return {
            'trades': 0, 'wins': 0, 'losses': 0, 'win_rate': 0.0,
            'realized_pnl': 0.0, 'expectancy_usd': 0.0, 'expectancy_pct': 0.0,
            'profit_factor': None, 'median_return_pct': 0.0, 'mean_return_pct': 0.0,
            'max_drawdown_usd': 0.0, 'max_loss_streak': 0,
            'mfe_avg_pct': 0.0, 'mae_avg_pct': 0.0,
            'confidence': 'insuficiente', 'priority_score': 0.0,
            'can_influence_priority': False,
        }
    pnls = [_f(x.get('realized_pnl')) for x in rows]
    rets = [_f(x.get('return_pct')) for x in rows]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x < 0]
    streak = 0
    for pnl in reversed(pnls):
        sign = 1 if pnl > 0 else -1 if pnl < 0 else 0
        if not sign or (streak and (streak > 0) != (sign > 0)):
            break
        streak += sign
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    pf = (gross_profit / gross_loss) if gross_loss else (float('inf') if gross_profit > 0 else None)
    return {
        'trades': n,
        'current_streak': streak,
        'recent_pnl_usd': round(sum(pnls[-20:]), 6),
        'recent_sample': min(20, n),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': round(len(wins) / n * 100.0, 2),
        'realized_pnl': round(sum(pnls), 6),
        'expectancy_usd': round(mean(pnls), 6),
        'expectancy_pct': round(mean(rets), 6),
        'profit_factor': None if pf is None else (999.0 if math.isinf(pf) else round(pf, 4)),
        'median_return_pct': round(median(rets), 6),
        'mean_return_pct': round(mean(rets), 6),
        'max_drawdown_usd': _max_drawdown_from_pnl(rows),
        'max_loss_streak': _loss_streak(rows),
        'mfe_avg_pct': round(mean([_f(x.get('mfe_pct')) for x in rows]), 6),
        'mae_avg_pct': round(mean([_f(x.get('mae_pct')) for x in rows]), 6),
        'confidence': _confidence(n),
        'priority_score': _priority_score(rows),
        'can_influence_priority': n >= MIN_SAMPLE,
    }


def _group_key(row):
    return '|'.join([
        str(row.get('strategy') or 'unknown'),
        str(row.get('symbol') or 'UNKNOWN'),
        str(row.get('timeframe') or 'unknown'),
        str(row.get('regime') or 'unknown'),
    ])


def summarize(journal):
    journal = list(journal or [])[-MAX_TRADES:]
    groups = {}
    for row in journal:
        groups.setdefault(_group_key(row), []).append(row)
    group_rows = []
    for key, rows in groups.items():
        sample = rows[-500:]
        summary = _summary_for(sample)
        first = sample[-1] if sample else {}
        group_rows.append({
            'key': key,
            'strategy': first.get('strategy'),
            'symbol': first.get('symbol'),
            'timeframe': first.get('timeframe'),
            'regime': first.get('regime') or 'unknown',
            **summary,
        })
    group_rows.sort(key=lambda x: (bool(x.get('can_influence_priority')), x.get('priority_score', 0), x.get('trades', 0)), reverse=True)
    return {
        'updated_at': _now(),
        'paper_only': True,
        'risk_authority': False,
        'live_authority': False,
        'min_sample_for_priority': MIN_SAMPLE,
        'overall': _summary_for(journal),
        'groups': group_rows[:100],
    }


def _trade_from_record(record):
    result = record.get('learning_result') or {}
    entry = record.get('entry_fill') or {}
    if not record.get('closed') or record.get('purpose') == 'TEST_LIFECYCLE':
        return None
    if not result.get('complete'):
        return None
    if record.get('ownership_conflict') or not record.get('baseline_flat'):
        return None
    if not record.get('client_order_id') or any(_f(v) <= 0 for v in (entry.get('price'), result.get('exit_price'), result.get('qty'))):
        return None
    if any(_f(result.get(k), None) is None for k in ('realized_pnl', 'return_pct', 'duration_s')):
        return None
    ctx = record.get('decision_context') or {}
    indicators = deepcopy(ctx.get('indicators') or {})
    return {
        'id': record.get('client_order_id'),
        'timestamp': result.get('closed_at') or record.get('closed_at') or _now(),
        'opened_at': entry.get('filled_at') or record.get('submitted_at'),
        'closed_at': result.get('closed_at'),
        'symbol': record.get('symbol'),
        'asset_class': ctx.get('asset_class') or 'us_equity',
        'strategy': record.get('strategy'),
        'timeframe': record.get('timeframe'),
        'signal': ctx.get('signal') or ('BUY' if record.get('side') == 'buy' else 'SELL'),
        'side': record.get('side'),
        'bar_time': ctx.get('bar_time'),
        'entry_price': _f(entry.get('price')),
        'exit_price': _f(result.get('exit_price')),
        'qty': _f(result.get('qty') or entry.get('qty')),
        'realized_pnl': _f(result.get('realized_pnl')),
        'return_pct': _f(result.get('return_pct')),
        'duration_s': int(_f(result.get('duration_s'))),
        'mfe_pct': _f(record.get('mfe_pct')),
        'mae_pct': _f(record.get('mae_pct')),
        'exit_reason': result.get('exit_reason') or record.get('trigger') or 'unknown',
        'regime': ctx.get('regime') or indicators.get('regime') or 'unknown',
        'volatility': ctx.get('volatility') if ctx.get('volatility') is not None else indicators.get('atr_pct'),
        'momentum': ctx.get('momentum'),
        'sentiment': ctx.get('sentiment') or 'neutral',
        'sentiment_score': _f(ctx.get('sentiment_score')),
        'news_sources': deepcopy((ctx.get('news_sources') or [])[:5]),
        'indicators': indicators,
        'risk_decision': ctx.get('risk_decision') or 'APROBADA',
        'entry_reason': ctx.get('entry_reason') or 'unknown',
        'risk_reason': ctx.get('risk_reason') or 'Todos los controles Risk superados',
        'order_created': True,
        'paper': True,
    }


def ingest(state):
    """Idempotently add newly closed Paper trades to the durable state journal."""
    journal = list(state.get('paper_learning_journal') or [])
    existing = {str(x.get('id')) for x in journal if x.get('id')}
    added = []
    for record in (state.get('position_ledger') or {}).values():
        trade = _trade_from_record(record)
        if not trade or str(trade.get('id')) in existing:
            continue
        journal.append(trade)
        existing.add(str(trade.get('id')))
        record['learning_processed_at'] = _now()
        added.append(trade)
    state['paper_learning_journal'] = journal
    state['paper_learning'] = summarize(journal)
    state['paper_learning_last_update'] = state['paper_learning']['updated_at']
    return {'added': added, 'summary': deepcopy(state['paper_learning'])}


def public_view(state, limit=25):
    journal = list(state.get('paper_learning_journal') or [])[-max(1, int(limit or 25)):]
    summary = deepcopy(state.get('paper_learning') or summarize(journal))
    return {
        'paper_only': True,
        'risk_authority': False,
        'live_authority': False,
        'journal_count': len(state.get('paper_learning_journal') or []),
        'recent': list(reversed(deepcopy(journal))),
        'summary': summary,
    }


def decision_context(signal=None, news=None, risk_decision='APROBADA', risk_reason=''):
    """Small bounded context snapshot for a Paper entry intent."""
    signal = signal or {}
    news = news or {}
    indicators = deepcopy(signal.get('indicators') or {})
    allowed_indicators = {}
    for key in ('sma20','sma50','rsi14','atr','atr14','atr_pct','regime','momentum','volatility'):
        if key in indicators:
            allowed_indicators[key] = indicators.get(key)
    sources = []
    for item in (news.get('items') or [])[:5]:
        if not isinstance(item, dict):
            continue
        sources.append({
            'title': str(item.get('title') or '')[:180],
            'url': str(item.get('url') or '')[:500],
            'sentiment': str(item.get('sentiment') or '')[:32],
            'score': _f(item.get('score')),
        })
    return {
        'captured_at': _now(),
        'entry_reason': str(signal.get('reason') or '')[:300],
        'signal': str(signal.get('signal') or '')[:16],
        'bar_time': signal.get('bar_time'),
        'indicators': allowed_indicators,
        'regime': indicators.get('regime') or 'unknown',
        'volatility': indicators.get('atr_pct') if indicators.get('atr_pct') is not None else indicators.get('volatility'),
        'momentum': indicators.get('momentum'),
        'sentiment': str(news.get('sentiment') or 'neutral')[:32],
        'sentiment_score': _f(news.get('sentiment_score')),
        'news_sources': sources,
        'risk_decision': str(risk_decision or 'APROBADA')[:32],
        'risk_reason': str(risk_reason or '')[:300],
        'asset_class': 'us_equity',
    }
