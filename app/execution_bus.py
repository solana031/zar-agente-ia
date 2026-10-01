"""Safe execution gateway and durable action bus for ZAR.

Interactive tool calls remain synchronous for backwards compatibility, but every
call passes through one policy/audit layer. Read-only external calls get a small
retry budget. The durable queue is available to sub-agents/background workers
without coupling them to the conversational model.
"""
import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .user_scope import safe_slug

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("ZAR_DATA_DIR", str(ROOT / "data")))

READ_ONLY_PREFIXES = ("gmail_get", "gmail_recent", "gmail_search", "gmail_status", "drive_", "calendar_upcoming", "calendar_status", "contacts_get", "contacts_search", "contacts_status", "google_workspace_status", "maps_", "web_", "file_", "zar_get", "zar_memory", "get_local_time", "sheets_read", "forms_get")
SENSITIVE = {"calendar_create_confirmed", "contacts_create", "contacts_update", "docs_create", "docs_append", "sheets_create", "sheets_write", "sheets_add_professional_table", "sheets_build_workbook", "sheets_upgrade_workbook", "slides_create", "slides_build_deck", "docs_build_report", "forms_create", "forms_add_question"}


def _db_file():
    d = DATA_DIR / "users" / safe_slug()
    d.mkdir(parents=True, exist_ok=True)
    return d / "zar_execution_bus.sqlite3"


def _conn():
    c = sqlite3.connect(str(_db_file()), timeout=20)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("""CREATE TABLE IF NOT EXISTS execution_events(
      id TEXT PRIMARY KEY, tool TEXT NOT NULL, policy TEXT NOT NULL, status TEXT NOT NULL,
      args_json TEXT NOT NULL, result_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS execution_queue(
      id TEXT PRIMARY KEY, action TEXT NOT NULL, payload_json TEXT NOT NULL, policy TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'queued', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT
    )""")
    c.commit()
    return c


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def policy_for(tool):
    if tool in SENSITIVE or tool.endswith("_confirmed"):
        return "sensitive"
    if tool.startswith(READ_ONLY_PREFIXES):
        return "read_only"
    return "standard"


def execute_with_policy(tool, args, executor):
    policy = policy_for(tool)
    event_id = str(uuid.uuid4())
    now = _now()
    with _conn() as c:
        c.execute("INSERT INTO execution_events(id,tool,policy,status,args_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                  (event_id, tool or "", policy, "running", json.dumps(args or {}, ensure_ascii=False), now, now))
        c.commit()
    max_attempts = 2 if policy == "read_only" else 1
    last = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = executor(tool, args)
            ok = not isinstance(result, dict) or result.get("ok", True) is not False
            if not ok and policy == "read_only" and attempt < max_attempts:
                time.sleep(0.25 * attempt); last = result; continue
            status = "completed" if ok else "failed"
            with _conn() as c:
                c.execute("UPDATE execution_events SET status=?,result_json=?,updated_at=?,attempts=?,last_error=? WHERE id=?",
                          (status, json.dumps(result, ensure_ascii=False, default=str)[:20000], _now(), attempt,
                           None if ok else str((result or {}).get("error", "tool_failed"))[:1000], event_id))
                c.commit()
            return result
        except Exception as exc:
            last = exc
            if attempt < max_attempts:
                time.sleep(0.25 * attempt); continue
            with _conn() as c:
                c.execute("UPDATE execution_events SET status='failed',updated_at=?,attempts=?,last_error=? WHERE id=?",
                          (_now(), attempt, str(exc)[:1000], event_id)); c.commit()
            raise
    return last


def enqueue(action, payload=None, policy="standard"):
    item_id = str(uuid.uuid4()); now = _now()
    with _conn() as c:
        c.execute("INSERT INTO execution_queue(id,action,payload_json,policy,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                  (item_id, action, json.dumps(payload or {}, ensure_ascii=False), policy, "queued", now, now)); c.commit()
    return {"id": item_id, "status": "queued", "action": action, "policy": policy}


def pending(limit=50):
    with _conn() as c:
        rows = c.execute("SELECT * FROM execution_queue WHERE status IN ('queued','retry') ORDER BY created_at LIMIT ?", (max(1, min(int(limit), 200)),)).fetchall()
    return [dict(r) for r in rows]
