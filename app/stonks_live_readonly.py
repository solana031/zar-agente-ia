"""Read-only Alpaca Live account bridge.

This module is intentionally incapable of creating, replacing or cancelling
orders. It exposes GET-only account telemetry for Real Money Readiness while
Live execution remains hard locked elsewhere.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import math
import os
import threading
import time

import requests

LIVE_BASE_URL = "https://api.alpaca.markets/v2"
DEFAULT_TTL_SECONDS = 30.0

_LOCK = threading.RLock()
_CACHE = {
    "expires_at": 0.0,
    "value": None,
}


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _credentials():
    # Deliberately different names from Paper credentials.
    return (
        os.environ.get("ALPACA_LIVE_READONLY_KEY", "").strip(),
        os.environ.get("ALPACA_LIVE_READONLY_SECRET", "").strip(),
    )


def configured():
    key, secret = _credentials()
    return bool(key and secret)


def _finite(value, default=0.0):
    try:
        n = float(value)
        return n if math.isfinite(n) else default
    except (TypeError, ValueError):
        return default


def _safe_money(value):
    return round(_finite(value), 2)


class LiveReadOnlyAdapter:
    """GET-only adapter. No write verbs or order mutation methods exist."""

    def __init__(self, get=requests.get, base_url=LIVE_BASE_URL, timeout=10):
        self._get = get
        self._base_url = str(base_url).rstrip("/")
        self._timeout = timeout

    @staticmethod
    def _headers(credentials):
        key, secret = credentials
        if not key or not secret:
            raise RuntimeError("Cuenta real read-only no configurada")
        return {
            "APCA-API-KEY-ID": key,
            "APCA-API-SECRET-KEY": secret,
            "Accept": "application/json",
        }

    def _request(self, path, credentials, params=None):
        response = self._get(
            self._base_url + path,
            headers=self._headers(credentials),
            params=params,
            timeout=self._timeout,
        )
        if not getattr(response, "ok", False):
            status = getattr(response, "status_code", "error")
            # Never echo broker body: it could contain identifiers or debug data.
            raise RuntimeError(f"Live read-only no disponible (HTTP {status})")
        data = response.json()
        if not isinstance(data, (dict, list)):
            raise RuntimeError("Respuesta Live read-only no valida")
        return data

    def account(self, credentials):
        return self._request("/account", credentials)

    def positions(self, credentials):
        return self._request("/positions", credentials)

    def open_orders(self, credentials):
        return self._request(
            "/orders",
            credentials,
            params={"status": "open", "limit": 100, "direction": "desc"},
        )

    def clock(self, credentials):
        return self._request("/clock", credentials)

    def snapshot(self, credentials):
        account = self.account(credentials)
        positions = self.positions(credentials)
        orders = self.open_orders(credentials)
        clock = self.clock(credentials)

        clean_positions = []
        exposure = 0.0
        unrealized = 0.0
        for row in positions if isinstance(positions, list) else []:
            if not isinstance(row, dict):
                continue
            market_value = _finite(row.get("market_value"))
            unrealized_pl = _finite(row.get("unrealized_pl"))
            exposure += abs(market_value)
            unrealized += unrealized_pl
            clean_positions.append({
                "symbol": str(row.get("symbol") or "")[:32],
                "asset_class": str(row.get("asset_class") or "")[:24],
                "qty": _finite(row.get("qty")),
                "market_value": round(market_value, 2),
                "unrealized_pl": round(unrealized_pl, 2),
                "unrealized_plpc": _finite(row.get("unrealized_plpc")),
            })

        clean_orders = []
        for row in orders if isinstance(orders, list) else []:
            if not isinstance(row, dict):
                continue
            clean_orders.append({
                "id": str(row.get("id") or "")[:80],
                "symbol": str(row.get("symbol") or "")[:32],
                "side": str(row.get("side") or "")[:16],
                "type": str(row.get("type") or "")[:16],
                "status": str(row.get("status") or "")[:24],
                "qty": _finite(row.get("qty")),
            })

        return {
            "state": "read_only",
            "connected": True,
            "configured": True,
            "read_only": True,
            "live_trading_enabled": False,
            "label": "LIVE TRADING BLOQUEADO",
            "equity": _safe_money(account.get("equity")),
            "cash": _safe_money(account.get("cash")),
            "buying_power": _safe_money(account.get("buying_power")),
            "portfolio_value": _safe_money(account.get("portfolio_value")),
            "exposure": round(exposure, 2),
            "unrealized_pl": round(unrealized, 2),
            "positions_count": len(clean_positions),
            "open_orders_count": len(clean_orders),
            "positions": clean_positions[:100],
            "open_orders": clean_orders[:100],
            "market_open": bool(clock.get("is_open")) if isinstance(clock, dict) else False,
            "next_open": str(clock.get("next_open") or "") if isinstance(clock, dict) else "",
            "next_close": str(clock.get("next_close") or "") if isinstance(clock, dict) else "",
            "updated_at": _now_iso(),
            "token_cost": 0,
            "orders_created": 0,
        }


def _not_connected():
    return {
        "state": "not_connected",
        "connected": False,
        "configured": False,
        "read_only": True,
        "live_trading_enabled": False,
        "label": "LIVE TRADING BLOQUEADO",
        "positions": [],
        "open_orders": [],
        "positions_count": 0,
        "open_orders_count": 0,
        "token_cost": 0,
        "orders_created": 0,
        "updated_at": _now_iso(),
    }


def status(force=False, adapter=None, ttl_seconds=DEFAULT_TTL_SECONDS):
    """Return a sanitized cached snapshot.

    Called by Readiness; at most one broker refresh per TTL, even if the UI
    polls Stonks every five seconds.
    """
    if not configured():
        return _not_connected()

    now = time.monotonic()
    with _LOCK:
        cached = _CACHE.get("value")
        if not force and cached is not None and now < float(_CACHE.get("expires_at") or 0):
            return deepcopy(cached)

    adapter = adapter or LiveReadOnlyAdapter()
    try:
        value = adapter.snapshot(_credentials())
    except Exception as exc:
        # Do not include exception repr or credentials.
        value = {
            "state": "error",
            "connected": False,
            "configured": True,
            "read_only": True,
            "live_trading_enabled": False,
            "label": "LIVE TRADING BLOQUEADO",
            "error": str(exc)[:180],
            "positions": [],
            "open_orders": [],
            "positions_count": 0,
            "open_orders_count": 0,
            "token_cost": 0,
            "orders_created": 0,
            "updated_at": _now_iso(),
        }

    with _LOCK:
        _CACHE["value"] = deepcopy(value)
        _CACHE["expires_at"] = time.monotonic() + max(5.0, float(ttl_seconds))
    return deepcopy(value)


def reset_cache():
    with _LOCK:
        _CACHE["value"] = None
        _CACHE["expires_at"] = 0.0
