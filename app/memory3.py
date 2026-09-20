"""ZAR Memory 3.0: semantic, temporal and importance-aware personal memory.

The module is deliberately additive: the existing Memory 2.0 SQLite/FTS store
continues to work, while Memory 3.0 adds a small user-scoped semantic index.
Embeddings use Gemini Embedding 2 when GEMINI_API_KEY is available; every path
has a deterministic lexical fallback so memory never depends on the embedding
service being online.
"""
import json
import math
import os
import re
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

from .model_router import model_for
from .user_scope import safe_slug

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("ZAR_DATA_DIR", str(ROOT / "data")))


def _db_file():
    d = DATA_DIR / "users" / safe_slug()
    d.mkdir(parents=True, exist_ok=True)
    return d / "zar_memory.sqlite3"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _conn():
    c = sqlite3.connect(str(_db_file()), timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("""CREATE TABLE IF NOT EXISTS memory3 (
        id TEXT PRIMARY KEY,
        text TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        memory_type TEXT NOT NULL,
        permanence TEXT NOT NULL,
        importance REAL NOT NULL DEFAULT 0.5,
        category TEXT NOT NULL DEFAULT 'general',
        status TEXT NOT NULL DEFAULT 'active',
        source TEXT NOT NULL DEFAULT 'user_explicit',
        expires_at TEXT,
        last_accessed_at TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        embedding_json TEXT,
        embedding_model TEXT
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_memory3_status ON memory3(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_memory3_updated ON memory3(updated_at)")
    c.commit()
    return c


_conn().close()


def _api_key():
    return os.environ.get("GEMINI_API_KEY", "").strip()


def _embedding(text):
    """Return a 768d Gemini Embedding 2 vector, or None if unavailable."""
    key = _api_key()
    if not key or not text.strip():
        return None
    model = model_for("embedding")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent"
    payload = {
        "model": f"models/{model}",
        "content": {"parts": [{"text": text[:8000]}]},
        "output_dimensionality": 768,
    }
    try:
        r = requests.post(
            url,
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
        if not r.ok:
            return None
        data = r.json()
        vals = ((data.get("embeddings") or [{}])[0] or {}).get("values") or []
        return [float(x) for x in vals] if vals else None
    except Exception:
        return None


def _cosine(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


def _tokens(text):
    return set(re.findall(r"[\wáéíóúüñÁÉÍÓÚÜÑ]{3,}", (text or "").lower(), re.UNICODE))


def _classify(text):
    t = (text or "").strip()
    low = t.lower()
    temporal = bool(re.search(
        r"\b(hoy|ahora|mañana|ayer|esta semana|este mes|actualmente|por ahora|durante|hasta el|hasta la|este fin de semana)\b",
        low,
    ))
    permanent = bool(re.search(
        r"\b(prefiero|me gusta|no me gusta|siempre|nunca|mi nombre|vivo en|trabajo en|trabajo de|mi proyecto|quiero que zar|no quiero que zar|mi restaurante|mi empresa|mi objetivo|mi idioma)\b",
        low,
    ))
    if temporal and not permanent:
        memory_type, permanence = "temporal", "temporary"
        if re.search(r"\b(hoy|ahora|mañana|ayer)\b", low):
            expires = datetime.now(timezone.utc) + timedelta(days=3)
        elif "semana" in low:
            expires = datetime.now(timezone.utc) + timedelta(days=10)
        else:
            expires = datetime.now(timezone.utc) + timedelta(days=30)
        expires_at = expires.isoformat(timespec="seconds")
    elif permanent:
        memory_type, permanence, expires_at = "preference", "persistent", None
    else:
        memory_type, permanence, expires_at = "fact", "persistent", None

    categories = {
        "project": r"\b(proyecto|zar|app|aplicación|web|android|iphone|github|railway|código|software)\b",
        "preference": r"\b(prefiero|me gusta|no me gusta|quiero que|no quiero que|estilo|forma)\b",
        "work": r"\b(trabajo|empresa|negocio|restaurante|cliente|proyecto laboral)\b",
        "location": r"\b(vivo|vivienda|casa|ciudad|madrid|majadahonda)\b",
        "planning": r"\b(mañana|hoy|semana|mes|fecha|cita|viaje|plan)\b",
    }
    category = next((k for k, p in categories.items() if re.search(p, low)), "general")
    importance = 0.72 if permanent else (0.58 if temporal else 0.50)
    if len(t) > 180:
        importance -= 0.04
    if category in {"project", "preference", "work"}:
        importance += 0.08
    importance = max(0.1, min(1.0, importance))
    return memory_type, permanence, round(importance, 3), category, expires_at


def upsert(memory_id, text, source="user_explicit", metadata=None):
    text = (text or "").strip()
    if not text:
        raise ValueError("El recuerdo está vacío.")
    memory_type, permanence, importance, category, expires_at = _classify(text)
    now = _now()
    metadata = dict(metadata or {})
    metadata.update({"memory_version": 3, "classification": "heuristic", "source": source})
    vector = _embedding(text)
    with _conn() as c:
        old = c.execute("SELECT created_at FROM memory3 WHERE id=?", (str(memory_id),)).fetchone()
        created = old[0] if old else now
        c.execute("""INSERT INTO memory3
            (id,text,created_at,updated_at,memory_type,permanence,importance,category,status,source,expires_at,last_accessed_at,metadata_json,embedding_json,embedding_model)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
              text=excluded.text, updated_at=excluded.updated_at,
              memory_type=excluded.memory_type, permanence=excluded.permanence,
              importance=excluded.importance, category=excluded.category,
              status=excluded.status, source=excluded.source,
              expires_at=excluded.expires_at, metadata_json=excluded.metadata_json,
              embedding_json=COALESCE(excluded.embedding_json,memory3.embedding_json),
              embedding_model=COALESCE(excluded.embedding_model,memory3.embedding_model)
        """, (
            str(memory_id), text, created, now, memory_type, permanence, importance,
            category, "active", source, expires_at, None,
            json.dumps(metadata, ensure_ascii=False),
            json.dumps(vector, ensure_ascii=False) if vector else None,
            model_for("embedding") if vector else None,
        ))
        c.commit()
    return get(memory_id)


def get(memory_id):
    with _conn() as c:
        row = c.execute("SELECT * FROM memory3 WHERE id=?", (str(memory_id),)).fetchone()
    return _row(row) if row else None


def _row(row):
    if not row:
        return None
    d = dict(row)
    try:
        d["metadata"] = json.loads(d.pop("metadata_json") or "{}")
    except Exception:
        d["metadata"] = {}
    try:
        d["embedding"] = json.loads(d.pop("embedding_json")) if d.get("embedding_json") else None
    except Exception:
        d["embedding"] = None
    d.pop("embedding_json", None)
    return d


def delete(memory_id):
    with _conn() as c:
        c.execute("DELETE FROM memory3 WHERE id=?", (str(memory_id),))
        c.commit()


def search(query, limit=12):
    q = (query or "").strip()
    if not q:
        return []
    q_tokens = _tokens(q)
    qvec = _embedding(q)
    now = datetime.now(timezone.utc)
    with _conn() as c:
        rows = c.execute("SELECT * FROM memory3 WHERE status='active' ORDER BY updated_at DESC LIMIT 500").fetchall()
    out = []
    for row in rows:
        item = _row(row)
        if item.get("expires_at"):
            try:
                if datetime.fromisoformat(item["expires_at"]) < now:
                    continue
            except Exception:
                pass
        text_tokens = _tokens(item["text"])
        lexical = len(q_tokens & text_tokens) / max(1, len(q_tokens))
        semantic = _cosine(qvec, item.get("embedding")) if qvec and item.get("embedding") else 0.0
        if qvec and item.get("embedding"):
            semantic = max(0.0, min(1.0, (semantic + 1.0) / 2.0))
        age_days = max(0.0, (now - datetime.fromisoformat(item["updated_at"]).replace(tzinfo=timezone.utc)).total_seconds() / 86400)
        freshness = 1.0 if age_days <= 1 else (0.8 if age_days <= 7 else (0.5 if age_days <= 30 else 0.2))
        score = (0.62 * semantic + 0.20 * lexical + 0.10 * item["importance"] + 0.08 * freshness) if qvec and item.get("embedding") else (0.62 * lexical + 0.25 * item["importance"] + 0.13 * freshness)
        if score < 0.12:
            continue
        item["relevance"] = round(max(0.0, min(1.0, score)), 4)
        item["semantic_score"] = round(semantic, 4)
        item["age_days"] = round(age_days, 2)
        item["provenance"] = item["source"]
        item["embedding_available"] = bool(item.get("embedding"))
        item.pop("embedding", None)
        out.append(item)
    out.sort(key=lambda x: (x["relevance"], x["importance"]), reverse=True)
    selected = out[: max(1, min(int(limit or 12), 20))]
    if selected:
        ids = [x["id"] for x in selected]
        with _conn() as c:
            c.executemany("UPDATE memory3 SET last_accessed_at=? WHERE id=?", [(_now(), i) for i in ids])
            c.commit()
    return selected


def stats():
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) FROM memory3 WHERE status='active'").fetchone()[0]
        persistent = c.execute("SELECT COUNT(*) FROM memory3 WHERE status='active' AND permanence='persistent'").fetchone()[0]
        temporal = c.execute("SELECT COUNT(*) FROM memory3 WHERE status='active' AND permanence='temporary'").fetchone()[0]
        embedded = c.execute("SELECT COUNT(*) FROM memory3 WHERE status='active' AND embedding_json IS NOT NULL").fetchone()[0]
        avg = c.execute("SELECT COALESCE(AVG(importance),0) FROM memory3 WHERE status='active'").fetchone()[0]
    return {"total": total, "persistent": persistent, "temporal": temporal, "embedded": embedded, "embedding_model": model_for("embedding"), "avg_importance": round(float(avg or 0), 3)}


def recent(limit=20):
    with _conn() as c:
        rows = c.execute("SELECT * FROM memory3 WHERE status='active' ORDER BY updated_at DESC LIMIT ?", (max(1, min(int(limit), 50)),)).fetchall()
    return [_row(r) for r in rows]


def reindex_existing(items):
    done = 0
    for item in items or []:
        try:
            upsert(item.get("id"), item.get("text", ""), source="legacy_memory2")
            done += 1
        except Exception:
            continue
    return {"indexed": done, "stats": stats()}
