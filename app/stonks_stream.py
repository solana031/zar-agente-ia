"""Real-time, zero-token market stream manager for ZAR Stonks.

Data-only component. It never calls an LLM and never sends orders. It maintains a
small in-memory cache of live Alpaca market data for equities/ETFs and crypto.
Options support is optional and disabled unless explicit contracts are configured.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
import threading
import time


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def _norm_equity(symbol):
    s = str(symbol or '').strip().upper()
    if not s or len(s) > 24:
        return None
    allowed = set('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-')
    return s if all(c in allowed for c in s) else None


def _norm_crypto(symbol):
    s = str(symbol or '').strip().upper().replace('-', '/')
    if '/' not in s and s:
        if s.endswith('USD') and len(s) > 3:
            s = s[:-3] + '/USD'
    allowed = set('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/')
    return s if s and len(s) <= 24 and all(c in allowed for c in s) else None


def _norm_option(symbol):
    s = str(symbol or '').strip().upper()
    return s if s and len(s) <= 32 and s.isalnum() else None


class MarketStreamManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._watch = {'equities': [], 'crypto': [], 'options': []}
        self._latest = {}
        self._ws = {}
        self._threads = {}
        self._restart = {'equities': threading.Event(), 'crypto': threading.Event(), 'options': threading.Event()}
        self._status = {
            'equities': self._blank_status('equities', 'IEX'),
            'crypto': self._blank_status('crypto', 'Alpaca crypto'),
            'options': self._blank_status('options', 'Indicative'),
        }
        self._started = False

    @staticmethod
    def _blank_status(kind, feed):
        return {
            'kind': kind, 'feed': feed, 'enabled': False, 'connected': False,
            'authenticated': False, 'last_message_at': None, 'last_error': None,
            'messages': 0, 'reconnects': 0, 'subscriptions': 0,
            'updated_at': _utcnow(), 'zero_tokens': True, 'order_authority': False,
        }

    def configure(self, equities=None, crypto=None, options=None):
        max_eq = max(1, min(30, int(os.environ.get('ZAR_STONKS_STREAM_MAX_EQUITIES', '30') or 30)))
        max_cr = max(1, min(50, int(os.environ.get('ZAR_STONKS_STREAM_MAX_CRYPTO', '20') or 20)))
        max_op = max(0, min(50, int(os.environ.get('ZAR_STONKS_STREAM_MAX_OPTIONS', '20') or 20)))
        eq = []
        for raw in equities or []:
            s = _norm_equity(raw)
            if s and s not in eq:
                eq.append(s)
        cr = []
        for raw in crypto or []:
            s = _norm_crypto(raw)
            if s and s not in cr:
                cr.append(s)
        op = []
        for raw in options or []:
            s = _norm_option(raw)
            if s and s not in op:
                op.append(s)
        plan = {'equities': eq[:max_eq], 'crypto': cr[:max_cr], 'options': op[:max_op]}
        changed = []
        closing = []
        with self._lock:
            for kind, items in plan.items():
                if self._watch.get(kind) != items:
                    self._watch[kind] = items
                    self._status[kind]['enabled'] = bool(items)
                    self._status[kind]['subscriptions'] = len(items)
                    self._status[kind]['updated_at'] = _utcnow()
                    changed.append(kind)
                    self._restart[kind].set()
                    ws = self._ws.get(kind)
                    if ws is not None:
                        closing.append(ws)
            allowed = {f'{kind}:{symbol}' for kind, items in plan.items() for symbol in items}
            self._latest = {k: v for k, v in self._latest.items() if k in allowed}
        # close() can wait for a callback that needs _lock.
        for ws in closing:
            try:
                ws.close()
            except Exception:
                pass
        self._ensure_threads()
        return {'changed': changed, 'watchlist': deepcopy(plan)}

    def _ensure_threads(self):
        with self._lock:
            if not self._started:
                self._started = True
            for kind in ('equities', 'crypto', 'options'):
                if not self._watch.get(kind):
                    continue
                t = self._threads.get(kind)
                if t and t.is_alive():
                    continue
                t = threading.Thread(target=self._run_loop, args=(kind,), name=f'zar-stonks-stream-{kind}', daemon=True)
                self._threads[kind] = t
                t.start()

    def _credentials(self):
        return (os.environ.get('ALPACA_PAPER_API_KEY', '').strip(), os.environ.get('ALPACA_PAPER_API_SECRET', '').strip())

    def _stream_url(self, kind):
        if kind == 'equities':
            feed = os.environ.get('ZAR_STONKS_EQUITY_STREAM_FEED', 'iex').strip().lower() or 'iex'
            return f'wss://stream.data.alpaca.markets/v2/{feed}', feed.upper()
        if kind == 'crypto':
            loc = os.environ.get('ZAR_STONKS_CRYPTO_STREAM_LOC', 'us').strip().lower() or 'us'
            return f'wss://stream.data.alpaca.markets/v1beta3/crypto/{loc}', f'CRYPTO/{loc.upper()}'
        feed = os.environ.get('ZAR_STONKS_OPTION_STREAM_FEED', 'indicative').strip().lower() or 'indicative'
        return f'wss://stream.data.alpaca.markets/v1beta1/{feed}', feed.upper()

    def _run_loop(self, kind):
        delay = 2.5
        wake = self._restart[kind]
        while True:
            with self._lock:
                symbols = list(self._watch.get(kind) or [])
                if not symbols:
                    # Remove atomically so configure() cannot miss starting a replacement.
                    self._threads.pop(kind, None)
                    self._ws.pop(kind, None)
                    self._status[kind].update(connected=False, authenticated=False)
                    return
                wake.clear()
            key, secret = self._credentials()
            started = time.monotonic()
            try:
                if not key or not secret:
                    raise RuntimeError('Credenciales Alpaca no configuradas')
                if kind == 'options':
                    self._run_options_once(kind, symbols, key, secret)
                else:
                    self._run_json_once(kind, symbols, key, secret)
            except Exception as exc:
                self._set_error(kind, str(exc)[:300])
            with self._lock:
                self._ws.pop(kind, None)
                self._status[kind]['connected'] = False
                self._status[kind]['authenticated'] = False
                self._status[kind]['reconnects'] += 1
                self._status[kind]['updated_at'] = _utcnow()
            if time.monotonic() - started >= 60:
                delay = 2.5
            if wake.wait(delay):
                delay = 2.5
            else:
                delay = min(60.0, delay * 2)

    def _current(self, kind, symbols):
        with self._lock:
            return self._watch[kind] == symbols and not self._restart[kind].is_set()

    def _run_json_once(self, kind, symbols, key, secret):
        try:
            import websocket
        except Exception as exc:
            raise RuntimeError('Falta websocket-client en el entorno') from exc
        url, feed = self._stream_url(kind)

        def on_open(ws):
            if not self._current(kind, symbols):
                ws.close()
                return
            with self._lock:
                self._status[kind].update(connected=True, authenticated=False, feed=feed, last_error=None, updated_at=_utcnow())
            ws.send(json.dumps({'action': 'auth', 'key': key, 'secret': secret}))

        def on_message(ws, raw):
            if not self._current(kind, symbols):
                ws.close()
                return
            try:
                payload = json.loads(raw)
            except Exception:
                return
            rows = payload if isinstance(payload, list) else [payload]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if row.get('T') == 'success' and row.get('msg') == 'authenticated':
                    with self._lock:
                        self._status[kind]['authenticated'] = True
                        self._status[kind]['updated_at'] = _utcnow()
                    sub = {'action': 'subscribe', 'trades': symbols, 'quotes': symbols, 'bars': symbols}
                    ws.send(json.dumps(sub))
                    continue
                if row.get('T') == 'error':
                    self._set_error(kind, f"{row.get('code')}: {row.get('msg')}")
                    ws.close()
                    return
                if row.get('T') == 'subscription':
                    with self._lock:
                        self._status[kind]['subscriptions'] = len(symbols)
                        self._status[kind]['updated_at'] = _utcnow()
                    continue
                self._ingest(kind, row)

        def on_error(ws, err):
            self._set_error(kind, str(err)[:300])

        def on_close(ws, code, msg):
            with self._lock:
                self._status[kind]['connected'] = False
                self._status[kind]['authenticated'] = False
                self._status[kind]['updated_at'] = _utcnow()

        ws = websocket.WebSocketApp(url, on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close)
        with self._lock:
            if not self._current(kind, symbols):
                return
            self._ws[kind] = ws
        ws.run_forever(ping_interval=20, ping_timeout=10)

    def _run_options_once(self, kind, symbols, key, secret):
        """Options stream uses MsgPack binary frames. Only explicit contracts are subscribed."""
        try:
            import websocket
            import msgpack
        except Exception as exc:
            raise RuntimeError('Faltan websocket-client/msgpack para opciones') from exc
        url, feed = self._stream_url(kind)

        def send_obj(ws, obj):
            ws.send(msgpack.packb(obj, use_bin_type=True), opcode=websocket.ABNF.OPCODE_BINARY)

        def on_open(ws):
            if not self._current(kind, symbols):
                ws.close()
                return
            with self._lock:
                self._status[kind].update(connected=True, authenticated=False, feed=feed, last_error=None, updated_at=_utcnow())
            send_obj(ws, {'action': 'auth', 'key': key, 'secret': secret})

        def on_data(ws, raw, opcode, fin):
            if not self._current(kind, symbols):
                ws.close()
                return
            if opcode != websocket.ABNF.OPCODE_BINARY:
                return
            try:
                payload = msgpack.unpackb(raw, raw=False)
            except Exception:
                return
            rows = payload if isinstance(payload, list) else [payload]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if row.get('T') == 'success' and row.get('msg') == 'authenticated':
                    with self._lock:
                        self._status[kind]['authenticated'] = True
                        self._status[kind]['updated_at'] = _utcnow()
                    send_obj(ws, {'action': 'subscribe', 'trades': symbols, 'quotes': symbols})
                    continue
                if row.get('T') == 'error':
                    self._set_error(kind, f"{row.get('code')}: {row.get('msg')}")
                    ws.close()
                    return
                self._ingest(kind, row)

        def on_error(ws, err):
            self._set_error(kind, str(err)[:300])

        def on_close(ws, code, msg):
            with self._lock:
                self._status[kind]['connected'] = False
                self._status[kind]['authenticated'] = False
                self._status[kind]['updated_at'] = _utcnow()

        ws = websocket.WebSocketApp(url, header=['Content-Type: application/msgpack'], on_open=on_open, on_data=on_data, on_error=on_error, on_close=on_close)
        with self._lock:
            if not self._current(kind, symbols):
                return
            self._ws[kind] = ws
        ws.run_forever(ping_interval=20, ping_timeout=10)

    def _set_error(self, kind, message):
        with self._lock:
            self._status[kind]['last_error'] = str(message or '')[:300]
            self._status[kind]['updated_at'] = _utcnow()

    def _ingest(self, kind, row):
        typ = row.get('T')
        symbol = str(row.get('S') or '').upper()
        if not symbol or typ not in ('t', 'q', 'b', 'u', 'd'):
            return
        try:
            stamp = datetime.fromisoformat(str(row.get('t') or '').replace('Z', '+00:00')).astimezone(timezone.utc)
        except (TypeError, ValueError):
            return
        channel = 'bar' if typ in ('b', 'u', 'd') else typ
        now = _utcnow()
        key = f'{kind}:{symbol}'
        with self._lock:
            if symbol not in self._watch[kind]:
                return
            rec = self._latest.setdefault(key, {
                'kind': kind, 'symbol': symbol, 'price': None, 'bid': None, 'ask': None,
                'bar_close': None, 'timestamp': None, 'updated_at': now, 'source': 'alpaca_stream'
            })
            previous = rec.get(channel + '_timestamp')
            if previous and stamp < datetime.fromisoformat(previous):
                return
            rec[channel + '_timestamp'] = stamp.isoformat()
            if typ == 't':
                if row.get('p') is not None:
                    rec['price'] = row.get('p')
                rec['trade_size'] = row.get('s')
            elif typ == 'q':
                rec['bid'] = row.get('bp')
                rec['ask'] = row.get('ap')
                try:
                    if rec['bid'] is not None and rec['ask'] is not None:
                        rec['mid'] = (float(rec['bid']) + float(rec['ask'])) / 2.0
                except Exception:
                    pass
            elif typ in ('b', 'u', 'd'):
                rec.update({
                    'open': row.get('o'), 'high': row.get('h'), 'low': row.get('l'),
                    'bar_close': row.get('c'), 'volume': row.get('v')
                })
                if rec.get('price') is None and row.get('c') is not None:
                    rec['price'] = row.get('c')
            rec['timestamp'] = max(rec.get('timestamp') or '', stamp.isoformat())
            rec['updated_at'] = now
            rec['message_type'] = typ
            self._status[kind]['messages'] += 1
            self._status[kind]['last_message_at'] = now
            self._status[kind]['updated_at'] = now

    def status(self, limit=30):
        with self._lock:
            feeds = deepcopy(self._status)
            watch = deepcopy(self._watch)
            rows = list(deepcopy(self._latest).values())
        now = datetime.now(timezone.utc)
        for row in rows:
            # Select the freshest available channel instead of preferring a stale trade.
            candidates = [(row.get('t_timestamp'), row.get('price')),
                          (row.get('q_timestamp'), row.get('mid')),
                          (row.get('bar_timestamp'), row.get('bar_close'))]
            candidates = [(t, p) for t, p in candidates if t and p is not None]
            if candidates:
                row['timestamp'], row['price'] = max(candidates, key=lambda x: x[0])
            age = (now - datetime.fromisoformat(row['timestamp'])).total_seconds()
            row['age_s'] = round(max(0, age), 1)
            row['stale'] = age > 120 or age < -5 or not feeds[row['kind']]['authenticated']
        rows.sort(key=lambda x: x.get('timestamp') or '', reverse=True)
        return {
            'architecture': 'realtime_zero_token_stream',
            'zero_tokens': True,
            'order_authority': False,
            'watchlist': watch,
            'feeds': feeds,
            'latest': rows[:max(1, int(limit or 30))],
            'updated_at': _utcnow(),
        }

    def reset_runtime(self):
        with self._lock:
            self._latest.clear()
            for kind in self._status:
                feed = self._status[kind].get('feed')
                self._status[kind] = self._blank_status(kind, feed)


MANAGER = MarketStreamManager()


def refresh_snapshot(snapshot, now=None):
    """Persisted stream health must expire even if the owner stops writing."""
    result = deepcopy(snapshot)
    now = now or datetime.now(timezone.utc)
    def age(value):
        try:
            stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            return (now - stamp).total_seconds()
        except (ValueError, TypeError):
            return float('inf')
    for feed in result.get('feeds', {}).values():
        if not -5 <= age(feed.get('last_message_at')) <= 120:
            feed.update(connected=False, authenticated=False, stale=True)
    for row in result.get('latest', []):
        elapsed = age(row.get('timestamp'))
        row['age_s'] = round(max(0, elapsed), 1) if elapsed != float('inf') else None
        row['stale'] = (not -5 <= elapsed <= 120 or
            not result.get('feeds', {}).get(row.get('kind'), {}).get('authenticated', False))
    return result
