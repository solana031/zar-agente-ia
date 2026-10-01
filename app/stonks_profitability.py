"""Deterministic Paper quality controls for ZAR Stonks v32.

This module does not predict returns and has no broker/order authority.  It only
filters autonomous Paper entry candidates to reduce weak/repetitive entries and
lets mature Paper-learning evidence influence priority conservatively.  Risk,
position sizing, Paper/Live mode and kill switches remain owned elsewhere.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import math

DEFAULT_MIN_QUALITY = 55.0
DEFAULT_COOLDOWN_MINUTES = 15
DEFAULT_MAX_ENTRIES_PER_SYMBOL_DAY = 4
MAX_TRACKED_DAYS = 14


def _f(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def _dt(value):
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _now(now=None):
    if isinstance(now, datetime):
        return now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def _learning_group(learning, symbol, strategy, timeframe, regime):
    groups = ((learning or {}).get('groups') or []) if isinstance(learning, dict) else []
    exact = None
    fallback = None
    for row in groups:
        if not isinstance(row, dict):
            continue
        if str(row.get('symbol') or '').upper() != str(symbol or '').upper():
            continue
        if str(row.get('strategy') or '') != str(strategy or '') or str(row.get('timeframe') or '') != str(timeframe or ''):
            continue
        fallback = fallback or row
        if str(row.get('regime') or 'unknown') == str(regime or 'unknown'):
            exact = row
            break
    return deepcopy(exact or fallback or {})


def _quality_score(signal, news=None, learning_group=None):
    """Return a descriptive 0-100 quality score for a Paper entry candidate.

    This is deliberately conservative and bounded.  It is not a probability of
    profit and never changes order size or Risk limits.
    """
    signal = signal or {}
    indicators = signal.get('indicators') or {}
    action = str(signal.get('signal') or '').upper()
    strategy = str(signal.get('strategy') or '').lower()
    if action not in ('BUY', 'SELL'):
        return 0.0, ['Señal no accionable']

    score = 50.0
    notes = ['Señal técnica confirmada en barra cerrada']
    rsi = indicators.get('rsi14')
    atr_pct = indicators.get('atr_pct')
    regime = str(indicators.get('regime') or 'unknown')

    if rsi is not None:
        rsi = _f(rsi, 50.0)
        if strategy == 'trend' and action == 'BUY':
            if 45 <= rsi <= 68:
                score += 14; notes.append('RSI compatible con continuación')
            elif rsi >= 78:
                score -= 22; notes.append('RSI extremadamente extendido')
            elif rsi >= 72:
                score -= 10; notes.append('RSI elevado')
        elif strategy == 'mean_reversion' and action == 'BUY':
            if 20 <= rsi < 30:
                score += 14; notes.append('RSI en zona de reversión')
            elif rsi < 15:
                score -= 10; notes.append('Sobreventa extrema; riesgo de caída continuada')

    if atr_pct is not None:
        atr_pct = _f(atr_pct)
        if 0.08 <= atr_pct <= 1.8:
            score += 10; notes.append('Volatilidad operativa normal')
        elif atr_pct > 3.5:
            score -= 22; notes.append('Volatilidad extrema')
        elif atr_pct > 2.3:
            score -= 10; notes.append('Volatilidad elevada')

    if action == 'BUY' and strategy == 'trend':
        if regime == 'tendencia_alcista':
            score += 10; notes.append('Régimen alineado')
        elif regime == 'alta_volatilidad':
            score -= 8; notes.append('Régimen de alta volatilidad')
    elif action == 'BUY' and strategy == 'mean_reversion':
        if regime == 'sobreventa':
            score += 8; notes.append('Régimen alineado con reversión')
        elif regime == 'alta_volatilidad':
            score -= 8; notes.append('Régimen de alta volatilidad')

    sentiment = str((news or {}).get('sentiment') or 'neutral').lower()
    sentiment_score = _f((news or {}).get('sentiment_score'))
    if action == 'BUY' and sentiment in ('negative', 'bearish') and sentiment_score <= -45:
        score -= 10; notes.append('Contexto público fuertemente negativo')
    elif action == 'BUY' and sentiment in ('positive', 'bullish') and sentiment_score >= 45:
        score += 5; notes.append('Contexto público favorable')

    lg = learning_group or {}
    if bool(lg.get('can_influence_priority')):
        priority = max(-100.0, min(100.0, _f(lg.get('priority_score'))))
        adjustment = max(-15.0, min(15.0, priority * 0.15))
        score += adjustment
        notes.append(f"Learning maduro ajusta prioridad {adjustment:+.1f}")

    return round(max(0.0, min(100.0, score)), 1), notes


def evaluate(state, symbol, strategy, timeframe, signal, news=None, learning=None, now=None):
    """Evaluate an autonomous Paper entry without touching Risk or broker state."""
    now = _now(now)
    action = str((signal or {}).get('signal') or '').upper()
    regime = str(((signal or {}).get('indicators') or {}).get('regime') or 'unknown')
    lg = _learning_group(learning, symbol, strategy, timeframe, regime)
    score, notes = _quality_score(signal, news, lg)
    threshold = max(0.0, min(100.0, _f(state.get('paper_min_signal_quality'), DEFAULT_MIN_QUALITY)))
    crypto = '/' in str(symbol or '').replace('-', '/')
    cooldown_m = max(0, int(_f(state.get('paper_crypto_cooldown_minutes') if crypto else state.get('paper_symbol_cooldown_minutes'), 3 if crypto else DEFAULT_COOLDOWN_MINUTES)))
    max_daily = max(1, int(_f(state.get('paper_crypto_max_entries_per_symbol_day') if crypto else state.get('paper_max_entries_per_symbol_day'), 16 if crypto else DEFAULT_MAX_ENTRIES_PER_SYMBOL_DAY)))
    reasons = []

    if action != 'BUY':
        reasons.append('El filtro de nuevas entradas solo autoriza BUY; SELL se reserva para salida de posición existente')

    last_map = state.get('paper_last_entry_at') or {}
    last = _dt(last_map.get(str(symbol).upper()))
    if last and cooldown_m:
        elapsed = (now - last).total_seconds() / 60.0
        if elapsed < cooldown_m:
            reasons.append(f'Cooldown activo: {elapsed:.1f}/{cooldown_m} min')

    day = now.date().isoformat()
    day_counts = state.get('paper_entry_counts') or {}
    count = int(((day_counts.get(day) or {}).get(str(symbol).upper())) or 0)
    if count >= max_daily:
        reasons.append(f'Límite diario por símbolo alcanzado: {count}/{max_daily}')

    if score < threshold:
        reasons.append(f'Calidad {score:.1f}/100 inferior al mínimo {threshold:.1f}')

    if lg and bool(lg.get('can_influence_priority')) and _f(lg.get('priority_score')) <= -45:
        reasons.append('Learning Paper maduro marca esta combinación con prioridad muy baja')

    return {
        'ok': not reasons,
        'paper_only': True,
        'order_authority': False,
        'risk_authority': False,
        'live_authority': False,
        'symbol': str(symbol or '').upper(),
        'strategy': str(strategy or ''),
        'timeframe': str(timeframe or ''),
        'signal': action,
        'bar_time': (signal or {}).get('bar_time'),
        'quality_score': score,
        'min_quality': threshold,
        'cooldown_minutes': cooldown_m,
        'entries_today': count,
        'max_entries_per_symbol_day': max_daily,
        'learning_sample': int(lg.get('trades') or 0) if lg else 0,
        'learning_priority_score': _f(lg.get('priority_score')) if lg else 0.0,
        'notes': notes[:8],
        'reasons': reasons[:8],
        'checked_at': now.isoformat(),
    }


def note_entry(state, symbol, now=None):
    """Record one accepted autonomous Paper entry; bounded housekeeping only."""
    now = _now(now)
    symbol = str(symbol or '').upper()
    if not symbol:
        return state
    state.setdefault('paper_last_entry_at', {})[symbol] = now.isoformat()
    counts = state.setdefault('paper_entry_counts', {})
    day = now.date().isoformat()
    counts.setdefault(day, {})[symbol] = int(counts.get(day, {}).get(symbol) or 0) + 1
    keep = sorted(counts.keys())[-MAX_TRACKED_DAYS:]
    state['paper_entry_counts'] = {k: counts[k] for k in keep}
    stats = state.setdefault('paper_quality_stats', {})
    stats['entries_accepted'] = int(stats.get('entries_accepted') or 0) + 1
    stats['last_entry_at'] = now.isoformat()
    stats['last_entry_symbol'] = symbol
    return state


def _evaluation_key(result):
    result = result or {}
    return '|'.join([
        str(result.get('symbol') or ''), str(result.get('strategy') or ''),
        str(result.get('timeframe') or ''), str(result.get('bar_time') or ''),
        str(result.get('signal') or ''),
    ])


def _mark_once(state, result):
    key = _evaluation_key(result)
    seen = state.setdefault('paper_quality_seen', {})
    if key and key in seen:
        return False
    if key:
        seen[key] = (result or {}).get('checked_at')
        if len(seen) > 256:
            for old in list(seen)[:len(seen)-256]:
                seen.pop(old, None)
    return True


def note_block(state, result):
    stats = state.setdefault('paper_quality_stats', {})
    fresh = _mark_once(state, result)
    if fresh:
        stats['candidates_seen'] = int(stats.get('candidates_seen') or 0) + 1
        stats['entries_blocked'] = int(stats.get('entries_blocked') or 0) + 1
    stats['last_score'] = _f((result or {}).get('quality_score'))
    stats['last_block_reason'] = '; '.join((result or {}).get('reasons') or [])[:500]
    stats['last_checked_at'] = (result or {}).get('checked_at')
    return state


def note_candidate(state, result):
    stats = state.setdefault('paper_quality_stats', {})
    if _mark_once(state, result):
        stats['candidates_seen'] = int(stats.get('candidates_seen') or 0) + 1
        stats['candidates_passed'] = int(stats.get('candidates_passed') or 0) + 1
    stats['last_score'] = _f((result or {}).get('quality_score'))
    stats['last_checked_at'] = (result or {}).get('checked_at')
    return state


def public_view(state):
    return {
        'enabled': bool(state.get('paper_profitability_enabled', True)),
        'paper_only': True,
        'risk_authority': False,
        'live_authority': False,
        'min_signal_quality': _f(state.get('paper_min_signal_quality'), DEFAULT_MIN_QUALITY),
        'symbol_cooldown_minutes': int(_f(state.get('paper_symbol_cooldown_minutes'), DEFAULT_COOLDOWN_MINUTES)),
        'max_entries_per_symbol_day': int(_f(state.get('paper_max_entries_per_symbol_day'), DEFAULT_MAX_ENTRIES_PER_SYMBOL_DAY)),
        'stats': deepcopy(state.get('paper_quality_stats') or {}),
    }
