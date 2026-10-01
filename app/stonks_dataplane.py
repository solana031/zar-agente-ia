"""Zero-token data plane for ZAR Stonks.

This module keeps fast Stonks supervision separate from model inference. Market/news
snapshots and deterministic features can be cached and routed without calling an LLM.
The AI gate only identifies candidate events; it never calls Gemini/OpenAI itself.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import os
import threading
import time


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def _safe_int(v, default=0):
    try:
        return int(v)
    except Exception:
        return int(default)


def _safe_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return float(default)


def _frame_seconds(timeframe):
    return {'1Min': 60, '5Min': 300, '15Min': 900}.get(str(timeframe or '1Min'), 60)


class ZeroTokenDataPlane:
    """Thread-safe cache + event router used by the autonomous Stonks worker."""

    MAX_CACHE = 512
    MAX_SCOPES = 64
    MAX_SYMBOLS = 128

    def __init__(self):
        self._lock = threading.RLock()
        self._cache = {}
        self._runtime = {}
        self._loads = [threading.Lock() for _ in range(32)]

    def _scope(self, scope_id):
        sid = str(scope_id or 'default')
        with self._lock:
            if sid not in self._runtime and len(self._runtime) >= self.MAX_SCOPES:
                self._runtime.pop(next(iter(self._runtime)))
            return self._runtime.setdefault(sid, {
                'started_at': _utcnow(),
                'cycles_total': 0,
                'zero_token_cycles': 0,
                'signal_cache_hits': 0,
                'signal_cache_misses': 0,
                'news_cache_hits': 0,
                'news_cache_misses': 0,
                'significant_events': 0,
                'ai_candidates': 0,
                'ai_calls': 0,
                'local_model_calls': 0,
                'last_event': None,
                'last_cycle_at': None,
                'last_cycle_zero_tokens': True,
                'last_signal_signatures': {},
                'last_news_signatures': {},
            })

    def hydrate(self, scope_id, persisted=None):
        if not isinstance(persisted, dict) or not persisted:
            return self.status(scope_id)
        s = self._scope(scope_id)
        with self._lock:
            if _safe_int(s.get('cycles_total')) == 0 and _safe_int(persisted.get('cycles_total')) > 0:
                for key in ('started_at','cycles_total','zero_token_cycles','signal_cache_hits','signal_cache_misses',
                            'news_cache_hits','news_cache_misses','significant_events','ai_candidates','ai_calls',
                            'local_model_calls','last_event','last_cycle_at','last_cycle_zero_tokens'):
                    if key in persisted:
                        s[key] = deepcopy(persisted[key])
        return self.status(scope_id)

    def begin_cycle(self, scope_id):
        s = self._scope(scope_id)
        with self._lock:
            s['cycles_total'] += 1
            s['zero_token_cycles'] += 1
            s['last_cycle_at'] = _utcnow()
            s['last_cycle_zero_tokens'] = True
        return self.status(scope_id)

    def record_ai_call(self, scope_id, provider='unknown', local=False):
        """Reserved for future on-demand AI integration."""
        s = self._scope(scope_id)
        with self._lock:
            if local:
                s['local_model_calls'] += 1
            else:
                s['ai_calls'] += 1
                # The current cycle is no longer zero-token if an API model was used.
                if s['last_cycle_zero_tokens']:
                    s['zero_token_cycles'] = max(0, s['zero_token_cycles'] - 1)
                s['last_cycle_zero_tokens'] = False
        return self.status(scope_id)

    def _cache_key(self, scope_id, kind, key):
        return (str(scope_id or 'default'), str(kind), str(key))

    def _cached(self, scope_id, kind, key, ttl, loader):
        ck = self._cache_key(scope_id, kind, key)
        # Striped locks collapse concurrent misses without holding the state lock
        # during I/O or accumulating one lock per temporal cache key.
        with self._loads[hash(ck) % len(self._loads)]:
            now = time.monotonic()
            with self._lock:
                for expired in [k for k, r in self._cache.items() if r['expires'] <= now]:
                    del self._cache[expired]
                row = self._cache.get(ck)
                if row:
                    return deepcopy(row['value']), True, max(0.0, now-row['mono'])
            value = loader()
            with self._lock:
                if ck not in self._cache and len(self._cache) >= self.MAX_CACHE:
                    self._cache.pop(next(iter(self._cache)))
                self._cache[ck] = {'mono': now, 'expires': now + max(0.0, float(ttl)),
                                   'value': deepcopy(value), 'updated_at': _utcnow()}
            return value, False, 0.0

    def signal(self, scope_id, symbol, strategy, timeframe, market_open, loader):
        """Refresh once per completed-bar window instead of every 5-second worker cycle."""
        frame = _frame_seconds(timeframe)
        if market_open:
            # A bucket changes when a new bar may have closed. Small grace prevents fetching
            # the just-opened bar repeatedly around the exact boundary.
            bucket = int((time.time() - 2.0) // frame)
            ttl = max(4.0, min(frame, 45.0))
            key = f'{symbol}|{strategy}|{timeframe}|{bucket}'
        else:
            # Closed market data does not need five-second refreshes.
            bucket = int(time.time() // 300)
            ttl = 300.0
            key = f'{symbol}|{strategy}|{timeframe}|closed|{bucket}'
        value, hit, age = self._cached(scope_id, 'signal', key, ttl, loader)
        s = self._scope(scope_id)
        with self._lock:
            s['signal_cache_hits' if hit else 'signal_cache_misses'] += 1
        return value, {'cached': hit, 'age_s': round(age, 2), 'key': key, 'ttl_s': ttl}

    def news(self, scope_id, symbol, loader, ttl=300.0):
        bucket = int(time.time() // max(60, int(ttl)))
        key = f'{symbol}|{bucket}'
        value, hit, age = self._cached(scope_id, 'news', key, ttl, loader)
        s = self._scope(scope_id)
        with self._lock:
            s['news_cache_hits' if hit else 'news_cache_misses'] += 1
        return value, {'cached': hit, 'age_s': round(age, 2), 'key': key, 'ttl_s': ttl}

    def route_event(self, scope_id, symbol, signal=None, news=None):
        """Detect state changes without model inference.

        Returns an event descriptor. `ai_candidate` means a future optional AI layer may be
        useful; no model call happens here.
        """
        s = self._scope(scope_id)
        symbol = str(symbol or '').upper()
        signal = signal or {}
        news = news or {}
        sig = '|'.join([
            str(signal.get('signal') or 'HOLD'),
            str(signal.get('bar_time') or ''),
            str((signal.get('indicators') or {}).get('regime') or ''),
        ])
        news_sig = '|'.join([
            str(news.get('sentiment') or 'neutral'),
            str(round(_safe_float(news.get('sentiment_score')), 1)),
            str(news.get('fetched_at') or ''),
        ])
        with self._lock:
            prev_sig = s['last_signal_signatures'].get(symbol)
            prev_news = s['last_news_signatures'].get(symbol)
            signal_changed = prev_sig is not None and prev_sig != sig
            news_changed = prev_news is not None and prev_news != news_sig
            first_seen = prev_sig is None
            if symbol not in s['last_signal_signatures'] and len(s['last_signal_signatures']) >= self.MAX_SYMBOLS:
                oldest = next(iter(s['last_signal_signatures']))
                s['last_signal_signatures'].pop(oldest, None)
                s['last_news_signatures'].pop(oldest, None)
            s['last_signal_signatures'][symbol] = sig
            s['last_news_signatures'][symbol] = news_sig

        actionable = str(signal.get('signal') or '').upper() in ('BUY', 'SELL')
        score = abs(_safe_float(news.get('sentiment_score')))
        strong_news = score >= 30.0 and str(news.get('sentiment') or 'neutral') != 'neutral'
        significant = (first_seen and actionable) or signal_changed or news_changed
        ai_candidate = bool(significant and actionable and (strong_news or signal_changed or news_changed))
        reasons = []
        if actionable: reasons.append('señal accionable')
        if signal_changed and not first_seen: reasons.append('cambio técnico')
        if news_changed: reasons.append('noticia/sentimiento nuevo')
        if strong_news: reasons.append('sentimiento público intenso')
        event = {
            'timestamp': _utcnow(), 'symbol': symbol,
            'significant': significant, 'ai_candidate': ai_candidate,
            'signal': signal.get('signal') or 'HOLD',
            'bar_time': signal.get('bar_time'),
            'sentiment': news.get('sentiment') or 'neutral',
            'sentiment_score': _safe_float(news.get('sentiment_score')),
            'reason': ', '.join(reasons) if reasons else 'sin cambios relevantes',
            'model_called': False,
        }
        with self._lock:
            if significant:
                s['significant_events'] += 1
                s['last_event'] = deepcopy(event)
            if ai_candidate:
                s['ai_candidates'] += 1
        return event

    def status(self, scope_id, persisted=None):
        with self._lock:
            s = deepcopy(self._scope(scope_id))
            bounds = {'cache_entries':len(self._cache), 'cache_limit':self.MAX_CACHE, 'scopes':len(self._runtime), 'scope_limit':self.MAX_SCOPES}
        if persisted and not s.get('cycles_total'):
            # Normally runtime wins; this fallback keeps a useful view immediately after restart.
            for k, v in dict(persisted).items():
                if k not in ('last_signal_signatures', 'last_news_signatures'):
                    s[k] = v
        naive_calls = _safe_int(s.get('cycles_total'))
        api_calls = _safe_int(s.get('ai_calls'))
        avoided = max(0, naive_calls - api_calls)
        baseline = max(100, _safe_int(os.environ.get('ZAR_STONKS_TOKEN_BASELINE_PER_CYCLE', '1200'), 1200))
        s.update({
            'runtime_bounds': bounds,
            'architecture': 'zero_token_data_plane',
            'ai_gate_enabled': False,
            'llm_calls_avoided_estimate': avoided,
            'estimated_tokens_avoided': avoided * baseline,
            'estimate_baseline_tokens_per_cycle': baseline,
            'signal_cache_total': _safe_int(s.get('signal_cache_hits')) + _safe_int(s.get('signal_cache_misses')),
            'news_cache_total': _safe_int(s.get('news_cache_hits')) + _safe_int(s.get('news_cache_misses')),
            'updated_at': _utcnow(),
        })
        # Runtime signatures are implementation detail; do not inflate persisted state/UI.
        s.pop('last_signal_signatures', None)
        s.pop('last_news_signatures', None)
        return s

    def sync_state(self, state, scope_id):
        state['data_plane_telemetry'] = self.status(scope_id, state.get('data_plane_telemetry'))
        return state

    def reset_runtime(self):
        """Test helper. Never called by production flow."""
        with self._lock:
            self._cache.clear()
            self._runtime.clear()


PLANE = ZeroTokenDataPlane()
