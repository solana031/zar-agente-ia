"""ZAR Holdings runtime.

One lightweight, persistent supervisor for ZAR's business units.  New business
modules are OFF by default and cannot spend money, publish content, contact
people or place financial orders without an explicitly configured connector and
an authorization flag stored in the company's config.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from .user_scope import safe_slug

_LOCK = threading.RLock()
_MAX_JOURNAL = 120
_MAX_LEDGER = 5000

COMPANIES = {
    "commerce": {"name": "ZAR Commerce", "icon": "🛒"},
    "media": {"name": "ZAR Media", "icon": "🎬"},
    "web_agency": {"name": "ZAR Web Agency", "icon": "🌐"},
    "sites": {"name": "ZAR Sites", "icon": "📰"},
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _root(scope_id):
    base = Path(os.environ.get("ZAR_DATA_DIR", "/data")) / "users" / safe_slug(scope_id) / "holdings"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _file(scope_id):
    return _root(scope_id) / "state.json"


def _company_default(key):
    meta = COMPANIES[key]
    return {
        "id": key,
        "name": meta["name"],
        "icon": meta["icon"],
        "state": "OFF",  # OFF | RUNNING | PAUSED
        "cycles": 0,
        "last_heartbeat": None,
        "last_action": "Sin actividad todavía.",
        "last_error": None,
        "started_at": None,
        "paused_at": None,
        "stopped_at": None,
        "metrics": {
            "revenue_collected": 0.0,
            "revenue_pending": 0.0,
            "costs": 0.0,
            "profit_realized": 0.0,
            "orders": 0,
            "sales": 0,
        },
        "config": {
            "autonomous": False,
            "allow_external_write": False,
            "daily_action_limit": 5,
            **({
                "allow_domain_reinvestment": False,
                "auto_domain_purchase": False,
                "max_domain_eur": 20.0,
                "domain_daily_budget_eur": 40.0,
                "auto_expand": False,
                "auto_deploy_vercel": True,
                "seed_topic": "guías útiles para ahorrar dinero en España",
                "max_sites": 12,
                "growth_cycle_interval": 360,
            } if key == "sites" else {}),
        },
        "queue": [],
        "journal": [],
    }


def default_state():
    return {
        "schema": 1,
        "version": "33.1.1",
        "global_stop": False,
        "global_stop_reason": "",
        "updated_at": _now(),
        "companies": {key: _company_default(key) for key in COMPANIES},
        "ledger": [],
        "runtime": {"cycles": 0, "last_heartbeat": None, "last_error": None},
    }


def _merge_company(key, current):
    base = _company_default(key)
    if isinstance(current, dict):
        for k, v in current.items():
            if k in {"metrics", "config"} and isinstance(v, dict):
                base[k].update(v)
            else:
                base[k] = v
    if base.get("state") not in {"OFF", "RUNNING", "PAUSED"}:
        base["state"] = "OFF"
    if not isinstance(base.get("journal"), list):
        base["journal"] = []
    if not isinstance(base.get("queue"), list):
        base["queue"] = []
    base["journal"] = base["journal"][-_MAX_JOURNAL:]
    return base


def ensure(state):
    base = default_state()
    if isinstance(state, dict):
        for k, v in state.items():
            if k not in {"companies", "runtime"}:
                base[k] = v
        if isinstance(state.get("runtime"), dict):
            base["runtime"].update(state["runtime"])
        current_companies = state.get("companies") or {}
        base["companies"] = {key: _merge_company(key, current_companies.get(key)) for key in COMPANIES}
    if not isinstance(base.get("ledger"), list):
        base["ledger"] = []
    base["ledger"] = base["ledger"][-_MAX_LEDGER:]
    return base


def read(scope_id):
    with _LOCK:
        try:
            return ensure(json.loads(_file(scope_id).read_text(encoding="utf-8")))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return default_state()


def write(scope_id, state):
    with _LOCK:
        data = ensure(state)
        data["updated_at"] = _now()
        path = _file(scope_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        return data


def _event(company, event, detail, **extra):
    row = {"id": uuid.uuid4().hex[:12], "timestamp": _now(), "event": event, "detail": str(detail)[:1600]}
    row.update({k: v for k, v in extra.items() if v is not None})
    company.setdefault("journal", []).append(row)
    company["journal"] = company["journal"][-_MAX_JOURNAL:]
    return row


def set_company_state(scope_id, key, action):
    if key not in COMPANIES:
        raise ValueError("Subempresa no válida.")
    action = str(action or "").lower().strip()
    with _LOCK:
        d = read(scope_id)
        c = d["companies"][key]
        now = _now()
        if action in {"start", "resume", "on"}:
            if d.get("global_stop"):
                raise RuntimeError("STOP GLOBAL activo. Desactívalo antes de arrancar una subempresa.")
            c.update(state="RUNNING", started_at=c.get("started_at") or now, paused_at=None, last_heartbeat=now, last_error=None)
            c["config"]["autonomous"] = True
            c["last_action"] = "Runtime autónomo encendido; procesará únicamente trabajo autorizado/configurado."
            _event(c, "START", c["last_action"])
        elif action in {"pause", "paused"}:
            c.update(state="PAUSED", paused_at=now, last_heartbeat=now)
            c["last_action"] = "Pausada; estado y cola conservados."
            _event(c, "PAUSE", c["last_action"])
        elif action in {"stop", "off"}:
            c.update(state="OFF", stopped_at=now, last_heartbeat=now)
            c["config"]["autonomous"] = False
            c["last_action"] = "Apagada; no iniciará acciones nuevas."
            _event(c, "STOP", c["last_action"])
        else:
            raise ValueError("Acción no válida.")
        d["companies"][key] = c
        return write(scope_id, d)


def set_global_stop(scope_id, enabled, reason=""):
    with _LOCK:
        d = read(scope_id)
        d["global_stop"] = bool(enabled)
        d["global_stop_reason"] = str(reason or ("STOP GLOBAL manual" if enabled else ""))[:500]
        if enabled:
            for c in d["companies"].values():
                if c.get("state") == "RUNNING":
                    c["state"] = "PAUSED"
                    c["paused_at"] = _now()
                    c["last_action"] = "Pausada por STOP GLOBAL."
                    _event(c, "GLOBAL_STOP", d["global_stop_reason"])
        return write(scope_id, d)


def update_company(scope_id, key, *, action=None, error=None, metrics=None, config=None, event=None, event_detail=None):
    with _LOCK:
        d = read(scope_id)
        c = d["companies"][key]
        c["last_heartbeat"] = _now()
        if action is not None:
            c["last_action"] = str(action)[:1600]
        if error is not None:
            c["last_error"] = str(error)[:1600] if error else None
        if metrics:
            c.setdefault("metrics", {}).update(metrics)
        if config:
            c.setdefault("config", {}).update(config)
        if event:
            _event(c, event, event_detail or action or event)
        d["companies"][key] = c
        return write(scope_id, d)


def complete_cycle(scope_id, key, action, *, error=None):
    with _LOCK:
        d = read(scope_id)
        c = d["companies"][key]
        if c.get("state") == "RUNNING":
            c["cycles"] = int(c.get("cycles") or 0) + 1
        c["last_heartbeat"] = _now()
        c["last_action"] = str(action or "Ciclo completado")[:1600]
        c["last_error"] = str(error)[:1600] if error else None
        _event(c, "CYCLE" if not error else "ERROR", c["last_action"], error=error)
        d["runtime"]["cycles"] = int(d["runtime"].get("cycles") or 0) + 1
        d["runtime"]["last_heartbeat"] = _now()
        if error:
            d["runtime"]["last_error"] = str(error)[:1600]
        return write(scope_id, d)


def queue_task(scope_id, key, kind, payload=None, *, requires_approval=False):
    with _LOCK:
        d = read(scope_id)
        c = d["companies"][key]
        task = {
            "id": uuid.uuid4().hex[:16],
            "kind": str(kind or "task")[:80],
            "payload": payload if isinstance(payload, dict) else {},
            "status": "AWAITING_APPROVAL" if requires_approval else "QUEUED",
            "requires_approval": bool(requires_approval),
            "created_at": _now(),
            "updated_at": _now(),
            "result": None,
            "error": None,
        }
        c.setdefault("queue", []).append(task)
        c["queue"] = c["queue"][-200:]
        _event(c, "QUEUE", f"{task['kind']} · {task['status']}", task_id=task["id"])
        write(scope_id, d)
        return task


def update_task(scope_id, key, task_id, **patch):
    with _LOCK:
        d = read(scope_id)
        c = d["companies"][key]
        found = None
        for task in c.get("queue") or []:
            if task.get("id") == task_id:
                for k, v in patch.items():
                    if k in {"status", "result", "error", "payload"}:
                        task[k] = v
                task["updated_at"] = _now()
                found = deepcopy(task)
                break
        if found is None:
            raise KeyError("Tarea no encontrada.")
        write(scope_id, d)
        return found


def next_task(scope_id, key, statuses=("QUEUED",)):
    d = read(scope_id)
    for task in d["companies"][key].get("queue") or []:
        if task.get("status") in statuses:
            return deepcopy(task)
    return None


def add_ledger(scope_id, company, kind, amount, *, currency="EUR", status="collected", source="manual", reference="", note="", verified=False):
    if company not in COMPANIES and company != "stonks":
        raise ValueError("Empresa no válida.")
    amount = round(float(amount), 6)
    row = {
        "id": uuid.uuid4().hex[:16], "timestamp": _now(), "company": company,
        "kind": str(kind or "revenue"), "amount": amount, "currency": str(currency or "EUR").upper(),
        "status": str(status or "collected"), "source": str(source or "manual"),
        "reference": str(reference or "")[:300], "note": str(note or "")[:1000], "verified": bool(verified),
    }
    with _LOCK:
        d = read(scope_id)
        # Idempotency for external synced rows.
        if row["reference"] and any(x.get("company") == company and x.get("reference") == row["reference"] and x.get("kind") == row["kind"] for x in d.get("ledger") or []):
            return next(x for x in d["ledger"] if x.get("company") == company and x.get("reference") == row["reference"] and x.get("kind") == row["kind"])
        d.setdefault("ledger", []).append(row)
        d["ledger"] = d["ledger"][-_MAX_LEDGER:]
        write(scope_id, d)
    recalculate(scope_id)
    return row


def recalculate(scope_id):
    with _LOCK:
        d = read(scope_id)
        for key in COMPANIES:
            revenue = pending = costs = 0.0
            sales = 0
            for x in d.get("ledger") or []:
                if x.get("company") != key:
                    continue
                amt = float(x.get("amount") or 0)
                kind = x.get("kind")
                status = x.get("status")
                if kind == "revenue":
                    if status == "collected":
                        revenue += amt; sales += 1
                    elif status == "pending":
                        pending += amt
                elif kind in {"cost", "expense"}:
                    costs += abs(amt)
            c = d["companies"][key]
            c["metrics"].update({
                "revenue_collected": round(revenue, 6),
                "revenue_pending": round(pending, 6),
                "costs": round(costs, 6),
                "profit_realized": round(revenue - costs, 6),
                "sales": sales,
            })
        return write(scope_id, d)


def public_view(scope_id):
    d = recalculate(scope_id)
    out = deepcopy(d)
    for c in out["companies"].values():
        c["journal"] = (c.get("journal") or [])[-20:][::-1]
        c["queue"] = (c.get("queue") or [])[-30:][::-1]
    out["ledger"] = (out.get("ledger") or [])[-100:][::-1]
    totals = {"revenue_collected": 0.0, "revenue_pending": 0.0, "costs": 0.0, "profit_realized": 0.0}
    for c in out["companies"].values():
        for k in totals:
            totals[k] += float(c.get("metrics", {}).get(k) or 0)
    out["totals"] = {k: round(v, 6) for k, v in totals.items()}
    return out


def active_scope_ids():
    base = Path(os.environ.get("ZAR_DATA_DIR", "/data")) / "users"
    if not base.exists():
        return []
    rows = []
    for path in base.glob("*/holdings/state.json"):
        try:
            d = ensure(json.loads(path.read_text(encoding="utf-8")))
            if any(c.get("state") == "RUNNING" for c in d.get("companies", {}).values()):
                rows.append(path.parent.parent.name)
        except Exception:
            continue
    return rows
