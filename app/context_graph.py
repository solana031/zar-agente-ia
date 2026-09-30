"""Small relational context graph layered on top of ZAR Memory 3.0.

Memory 3.0 already provides vector + lexical retrieval. This graph adds explicit
relationships between the objects ZAR is actively working with so anaphoric
references can be resolved without injecting broad history into every prompt.
"""
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .user_scope import safe_slug

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("ZAR_DATA_DIR", str(ROOT / "data")))


def _db_file():
    d = DATA_DIR / "users" / safe_slug()
    d.mkdir(parents=True, exist_ok=True)
    return d / "zar_context_graph.sqlite3"


def _conn():
    c = sqlite3.connect(str(_db_file()), timeout=20)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("""CREATE TABLE IF NOT EXISTS graph_nodes(
        id TEXT PRIMARY KEY, kind TEXT NOT NULL, label TEXT NOT NULL,
        payload_json TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS graph_edges(
        source_id TEXT NOT NULL, target_id TEXT NOT NULL, relation TEXT NOT NULL,
        updated_at TEXT NOT NULL, PRIMARY KEY(source_id,target_id,relation)
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_graph_kind ON graph_nodes(kind)")
    c.commit()
    return c


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _tokens(text):
    return set(re.findall(r"[\wáéíóúüñ]{3,}", (text or "").lower(), re.I))


def upsert_node(node_id, kind, label, payload=None):
    if not node_id:
        return
    with _conn() as c:
        c.execute("""INSERT INTO graph_nodes(id,kind,label,payload_json,updated_at)
        VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET kind=excluded.kind,label=excluded.label,
        payload_json=excluded.payload_json,updated_at=excluded.updated_at""",
        (str(node_id), kind, label or kind, json.dumps(payload or {}, ensure_ascii=False), _now()))
        c.commit()


def link(source_id, target_id, relation):
    if not source_id or not target_id:
        return
    with _conn() as c:
        c.execute("""INSERT INTO graph_edges(source_id,target_id,relation,updated_at)
        VALUES(?,?,?,?) ON CONFLICT(source_id,target_id,relation) DO UPDATE SET updated_at=excluded.updated_at""",
        (str(source_id), str(target_id), relation, _now()))
        c.commit()


def sync_runtime_context(ctx, memory_hits=None):
    ctx = ctx or {}
    root = "runtime:active"
    upsert_node(root, "runtime", "Contexto activo de ZAR", {"focus": ctx.get("focus") or {}})
    specs = [
        ("active_email", "email", ctx.get("active_email") or {}),
        ("pending_email", "draft", ctx.get("pending_email") or {}),
        ("last_contact", "contact", ctx.get("last_contact") or {}),
        ("task", "task", ctx.get("task") or {}),
        ("last_uploaded_file", "file", ctx.get("last_uploaded_file") or {}),
        ("last_video_project", "video_project", ctx.get("last_video_project") or {}),
    ]
    for key, kind, obj in specs:
        if not obj:
            continue
        oid = obj.get("id") or obj.get("thread_id") or obj.get("email") or obj.get("name") or key
        nid = f"{kind}:{oid}"
        label = obj.get("subject") or obj.get("name") or obj.get("summary") or obj.get("email") or kind
        upsert_node(nid, kind, str(label), obj)
        link(root, nid, "active")
    for item in memory_hits or []:
        mid = item.get("id")
        if not mid:
            continue
        nid = f"memory:{mid}"
        upsert_node(nid, "memory", (item.get("text") or "")[:240], {
            "text": item.get("text", ""), "category": item.get("category", "general"),
            "relevance": item.get("relevance", 0),
        })
        link(root, nid, "relevant_memory")


def relevant_context(query, limit=8, max_chars=5000):
    q = _tokens(query)
    with _conn() as c:
        rows = c.execute("SELECT * FROM graph_nodes ORDER BY updated_at DESC LIMIT 200").fetchall()
        edges = c.execute("SELECT * FROM graph_edges ORDER BY updated_at DESC LIMIT 300").fetchall()
    edge_map = {}
    for e in edges:
        edge_map.setdefault(e["source_id"], []).append((e["relation"], e["target_id"]))
        edge_map.setdefault(e["target_id"], []).append((e["relation"], e["source_id"]))
    scored = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except Exception:
            payload = {}
        hay = f"{row['label']} {json.dumps(payload, ensure_ascii=False)}"
        toks = _tokens(hay)
        lexical = len(q & toks) / max(1, len(q)) if q else 0.0
        active_bonus = 0.35 if row["id"] == "runtime:active" or any(rel == "active" for rel, _ in edge_map.get(row["id"], [])) else 0.0
        score = lexical + active_bonus
        if score <= 0 and q:
            continue
        scored.append((score, row, payload))
    scored.sort(key=lambda x: x[0], reverse=True)
    lines = []
    total = 0
    for score, row, payload in scored[:max(1, int(limit))]:
        related = [f"{rel}->{target}" for rel, target in edge_map.get(row["id"], [])[:4]]
        compact = json.dumps(payload, ensure_ascii=False)[:900]
        line = f"- [{row['kind']}] {row['label']} | relaciones: {', '.join(related) or 'ninguna'} | {compact}"
        if total + len(line) > max_chars:
            break
        lines.append(line); total += len(line)
    return "\n".join(lines)
