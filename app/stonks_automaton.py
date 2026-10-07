"""ZAR Stonks Automaton Mode.

A lightweight, Paper-only orchestration state inspired by Conway Automaton's
continuous Think -> Act -> Observe -> Repeat loop.  It has no broker access and
cannot bypass ZAR Decision/Risk.  The existing Stonks engine remains the single
execution authority.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

MAX_JOURNAL = 80
STATES = {'OFF','STARTING','ACTIVE','PAUSED','STOPPING','ERROR'}


def _now():
    return datetime.now(timezone.utc).isoformat()


def default_state():
    return {
        "state": "OFF",
        "phase": "IDLE",
        "cycles": 0,
        "last_heartbeat": None,
        "started_at": None,
        "paused_at": None,
        "stopped_at": None,
        "last_asset": None,
        "last_decision": "Sin decisiones todavía.",
        "last_action": "Automaton apagado.",
        "last_result": None,
        "last_learning": None,
        "trades": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": 0.0,
        "pnl_usd": 0.0,
        "baseline_trades": 0,
        "baseline_wins": 0,
        "baseline_losses": 0,
        "baseline_pnl_usd": 0.0,
        "journal": [],
        "paper_only": True,
        "live_authority": False,
        "risk_authority": False,
    }


def ensure(container):
    current = container.get("automaton") if isinstance(container, dict) else None
    base = default_state()
    if isinstance(current, dict):
        base.update(current)
    if base.get('state') == 'RUNNING':
        base['state'] = 'ACTIVE'  # persisted pre-33.3.4 state
    if base.get("state") not in STATES:
        base["state"] = "OFF"
    if not isinstance(base.get("journal"), list):
        base["journal"] = []
    base["journal"] = base["journal"][-MAX_JOURNAL:]
    container["automaton"] = base
    return base


def _event(auto, event, detail, **extra):
    row = {"timestamp": _now(), "event": event, "detail": str(detail)[:1200]}
    row.update({k: v for k, v in extra.items() if v is not None})
    auto.setdefault("journal", []).append(row)
    auto["journal"] = auto["journal"][-MAX_JOURNAL:]
    return row


def start(container):
    auto = ensure(container)
    if auto['state'] in {'STARTING','ACTIVE'}:
        return auto
    if auto['state']=='STOPPING':
        raise ValueError('Espera al apagado antes de encender.')
    now = _now()
    if auto.get("state") == "OFF":
        overall = ((container.get("paper_learning") or {}).get("overall") or {})
        auto["baseline_trades"] = int(overall.get("trades") or 0)
        auto["baseline_wins"] = int(overall.get("wins") or 0)
        auto["baseline_losses"] = int(overall.get("losses") or 0)
        auto["baseline_pnl_usd"] = float(overall.get("realized_pnl") or 0.0)
        auto["trades"] = auto["wins"] = auto["losses"] = 0
        auto["win_rate"] = auto["pnl_usd"] = 0.0
    auto.update(state="STARTING", phase="PREFLIGHT", started_at=now, paused_at=None,
                last_heartbeat=None, error=None, last_action="Esperando heartbeat real del motor.")
    _event(auto, "START", "Automaton Mode encendido · Paper-only")
    return auto


def pause(container):
    auto = ensure(container)
    if auto['state'] not in {'ACTIVE','STARTING','PAUSED'}:
        raise ValueError('Automaton no está activo.')
    now = _now()
    auto.update(state="PAUSED", phase="PAUSED", paused_at=now,
                last_action="Automaton pausado; no se abrirán nuevas acciones autónomas.")
    _event(auto, "PAUSE", "Automaton pausado; estado y aprendizaje conservados")
    return auto


def stop(container):
    auto = ensure(container)
    now = _now()
    auto.update(state="OFF", phase="IDLE", stopped_at=now,
                last_action="Automaton apagado; estado persistido.")
    _event(auto, "STOP", "Automaton apagado; no iniciará nuevas acciones")
    return auto

def stopping(container):
    auto=ensure(container)
    if auto['state']!='OFF':
        auto.update(state='STOPPING',phase='STOPPING')
        _event(auto,'STOPPING','Entradas desactivadas; finalizando control del motor')
    return auto

def fail(container, reason):
    auto=ensure(container)
    if auto['state'] in {'STARTING','ACTIVE','PAUSED'}:
        auto.update(state='ERROR',phase='ERROR',error=str(reason)[:300])
        container['paused']=True
        _event(auto,'ERROR',reason)
    return auto


def heartbeat(container, phase="THINK", asset=None, detail=None):
    auto = ensure(container)
    auto["last_heartbeat"] = _now()
    if auto['state']=='STARTING':
        auto['state']='ACTIVE'
        _event(auto,'ACTIVE','Ciclo real del motor recibido; preflight superado')
    auto["phase"] = phase
    if asset:
        auto["last_asset"] = asset
    if detail:
        auto["last_action"] = str(detail)[:1200]
    return auto


def complete_cycle(container, *, action="Sin señales.", trace=None, learning=None):
    auto = ensure(container)
    if auto.get("state") != "ACTIVE":
        return auto
    auto["cycles"] = int(auto.get("cycles") or 0) + 1
    auto["phase"] = "REPEAT"
    auto["last_heartbeat"] = _now()
    auto["last_action"] = str(action or "Sin señales.")[:1200]
    if trace:
        # Pick the last meaningful specialist message as the summarized decision.
        for row in reversed(list(trace)):
            data = row.get("data") or {}
            symbol = data.get("symbol")
            if symbol:
                auto["last_asset"] = symbol
            detail = row.get("detail")
            if detail and row.get("agent") in {"execution", "paper_quality", "analysis", "risk", "decision"}:
                auto["last_decision"] = str(detail)[:800]
                break
    if learning:
        overall = (learning.get("overall") or {}) if isinstance(learning, dict) else {}
        auto["trades"] = max(0, int(overall.get("trades") or 0) - int(auto.get("baseline_trades") or 0))
        auto["wins"] = max(0, int(overall.get("wins") or 0) - int(auto.get("baseline_wins") or 0))
        auto["losses"] = max(0, int(overall.get("losses") or 0) - int(auto.get("baseline_losses") or 0))
        auto["win_rate"] = round((auto["wins"] / auto["trades"] * 100.0), 2) if auto["trades"] else 0.0
        auto["pnl_usd"] = round(float(overall.get("realized_pnl") or 0.0) - float(auto.get("baseline_pnl_usd") or 0.0), 6)
        groups = learning.get("groups") or []
        if groups:
            g = groups[0]
            auto["last_learning"] = (
                f"{g.get('symbol') or 'activo'} · {g.get('strategy') or 'estrategia'} · "
                f"muestra {g.get('trades') or 0} · score {g.get('priority_score') or 0}"
            )
    _event(auto, "CYCLE", auto["last_action"], asset=auto.get("last_asset"), phase="REPEAT")
    return auto


def public_view(container):
    auto = deepcopy(ensure(container))
    if auto['state'] in {'STARTING','ACTIVE','PAUSED'}:
        stamp=auto.get('last_heartbeat') or auto.get('started_at')
        try:
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(stamp)).total_seconds()
        except (TypeError,ValueError):
            age=None
        auto['heartbeat_age_seconds']=age
        auto['heartbeat_verified']=bool(auto.get('last_heartbeat') and age is not None and 0<=age<=90)
        if age is None or age>90:
            auto.update(state='ERROR',error='Heartbeat del motor ausente/caducado; verificar antes de reanudar.')
    auto["journal"] = auto.get("journal", [])[-20:][::-1]
    return auto
