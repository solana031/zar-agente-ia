"""Memoria persistente y base de conocimiento local de Zar.

Guarda conversaciones completas, recuerdos explícitos, texto de archivos y
metadatos de archivos/proyectos en SQLite dentro de ZAR_DATA_DIR. No depende
de Google: el índice local funciona aunque Google esté desconectado.
"""
import hashlib
import json
import os
from .user_scope import safe_slug
import re
import sqlite3
import zipfile
from datetime import datetime, timezone
import math
from difflib import SequenceMatcher
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("ZAR_DATA_DIR", str(ROOT / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_FILE = DATA_DIR / "zar_memory.sqlite3"

def _db_file():
    d = DATA_DIR / "users" / safe_slug()
    d.mkdir(parents=True, exist_ok=True)
    return d / "zar_memory.sqlite3"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _conn():
    c = sqlite3.connect(str(_db_file()), timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("CREATE TABLE IF NOT EXISTS sources (id TEXT PRIMARY KEY, source_type TEXT NOT NULL, source_id TEXT, title TEXT, meta_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS chunks (id TEXT PRIMARY KEY, source_id TEXT NOT NULL, chunk_index INTEGER NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE CASCADE)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id)")
    c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(content, title, source_type, source_id UNINDEXED, chunk_id UNINDEXED)")
    c.execute("CREATE TABLE IF NOT EXISTS migrations (name TEXT PRIMARY KEY, done_at TEXT NOT NULL)")
    c.commit()
    return c


def init_db():
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS sources (
            id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL,
            source_id TEXT,
            title TEXT,
            meta_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS chunks (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE CASCADE
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id)")
        c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(content, title, source_type, source_id UNINDEXED, chunk_id UNINDEXED)")
        c.execute("CREATE TABLE IF NOT EXISTS migrations (name TEXT PRIMARY KEY, done_at TEXT NOT NULL)")
        c.commit()


init_db()


def _hash(*parts):
    raw = "\x1f".join(str(x or "") for x in parts)
    return hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()


def _chunks(text, size=2800, overlap=350):
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    out = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            cut = text.rfind(" ", start + size // 2, end)
            if cut > start:
                end = cut
        out.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return out


def index_source(source_type, source_id, title, text, meta=None):
    """Indexa una fuente completa. Reindexar la misma fuente reemplaza sus chunks."""
    source_key = _hash(source_type, source_id or title)
    pieces = _chunks(text)
    now = _now()
    with _conn() as c:
        old = c.execute("SELECT id FROM sources WHERE id=?", (source_key,)).fetchone()
        if old:
            ids = [r[0] for r in c.execute("SELECT id FROM chunks WHERE source_id=?", (source_key,)).fetchall()]
            for cid in ids:
                c.execute("DELETE FROM chunks_fts WHERE chunk_id=?", (cid,))
            c.execute("DELETE FROM chunks WHERE source_id=?", (source_key,))
            c.execute("DELETE FROM sources WHERE id=?", (source_key,))
        c.execute("INSERT INTO sources VALUES (?,?,?,?,?,?,?)", (
            source_key, source_type, str(source_id or ""), title or "", json.dumps(meta or {}, ensure_ascii=False), now, now
        ))
        for i, piece in enumerate(pieces):
            cid = _hash(source_key, i, piece)
            c.execute("INSERT INTO chunks VALUES (?,?,?,?,?)", (cid, source_key, i, piece, now))
            c.execute("INSERT INTO chunks_fts(content,title,source_type,source_id,chunk_id) VALUES (?,?,?,?,?)", (piece, title or "", source_type, str(source_id or ""), cid))
        c.commit()
    return {"source_id": source_key, "chunks": len(pieces)}


def index_message(role, content, message_id=None):
    mid = message_id or _hash(role, content, _now())
    return index_source("chat", mid, f"Conversación · {role}", content, {"role": role})


def index_memory(memory_id, text, meta=None):
    return index_source("memory", memory_id, "Recuerdo de Zar", text, meta or {"provenance": "user_explicit", "memory_version": 2})


def index_file(item, text=None):
    item = item or {}
    fid = item.get("id", "")
    title = item.get("name", "Archivo")
    meta = {k: item.get(k) for k in ("name", "mime", "category", "note", "created_at", "updated_at")}
    return index_source("file", fid, title, text or item.get("note", ""), meta)


def index_artifact(artifact_id, title, description, meta=None):
    return index_source("artifact", artifact_id, title, description, meta or {})


def delete_source(source_type, source_id):
    source_key = _hash(source_type, source_id)
    with _conn() as c:
        ids = [r[0] for r in c.execute("SELECT id FROM chunks WHERE source_id=?", (source_key,)).fetchall()]
        for cid in ids:
            c.execute("DELETE FROM chunks_fts WHERE chunk_id=?", (cid,))
        c.execute("DELETE FROM chunks WHERE source_id=?", (source_key,))
        c.execute("DELETE FROM sources WHERE id=?", (source_key,))
        c.commit()


# Common Spanish stopwords: removing them improves retrieval without requiring
# an external embedding service. This is deliberately local and deterministic.
_STOPWORDS = {
    "a","al","algo","algunas","algunos","ante","antes","como","con","contra","cual","cuando",
    "de","del","desde","donde","dos","el","ella","ellas","ellos","en","entre","era","es","esa",
    "ese","eso","esta","estas","este","esto","estos","ha","hacia","hasta","hay","la","las","le",
    "les","lo","los","me","mi","mis","muy","no","nos","o","para","pero","por","que","qué",
    "se","sea","si","sin","sobre","son","su","sus","te","tengo","tu","tus","un","una","uno",
    "unos","y","ya","yo","del","cómo","dime","quiero","puedes","puede","pueden"
}


def _tokens(text):
    raw = re.findall(r"[\wáéíóúüñÁÉÍÓÚÜÑ]{2,}", (text or "").lower(), flags=re.UNICODE)
    return [t for t in raw if t not in _STOPWORDS]


def _age_days(iso):
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 86400.0)
    except Exception:
        return 99999.0


def _freshness(age_days):
    # Freshness is a modest tie-breaker, not a replacement for relevance.
    if age_days <= 1: return 1.0
    if age_days <= 7: return 0.75
    if age_days <= 30: return 0.45
    if age_days <= 180: return 0.20
    return 0.05


def _source_boost(source_type):
    return {
        "memory": 1.18,
        "chat": 1.08,
        "google_task": 1.05,
        "google_calendar": 1.04,
        "google_contact": 1.02,
        "google_gmail": 1.00,
        "google_drive_content": 0.98,
        "file": 0.98,
        "artifact": 0.94,
    }.get(source_type, 0.92)


def search_hybrid(query, limit=10):
    """Hybrid local retrieval: FTS/BM25 + token overlap + freshness + provenance.

    This is intentionally dependency-free. It behaves like a lightweight semantic
    layer today and leaves room for optional embeddings later without changing the
    public search API.
    """
    q = (query or "").strip()
    q_tokens = _tokens(q)
    if not q_tokens:
        return []
    limit = max(1, min(int(limit or 10), 20))
    candidates = {}
    with _conn() as c:
        # First pass: exact phrase-ish FTS. AND gives high precision.
        try:
            match = " AND ".join('"' + t.replace('"', '') + '"' for t in q_tokens[:12])
            rows = c.execute("""SELECT f.source_type, f.source_id, f.title, f.content, f.chunk_id,
                                      s.created_at, s.updated_at, s.meta_json,
                                      bm25(chunks_fts) AS bm25_score
                               FROM chunks_fts f JOIN sources s ON s.id = (SELECT source_id FROM chunks WHERE id=f.chunk_id)
                               WHERE chunks_fts MATCH ? ORDER BY bm25_score LIMIT ?""", (match, min(limit * 4, 80))).fetchall()
        except Exception:
            rows = []
        # Second pass: OR broad recall.
        if len(rows) < limit * 2:
            try:
                match_or = " OR ".join('"' + t.replace('"', '') + '"' for t in q_tokens[:12])
                rows2 = c.execute("""SELECT f.source_type, f.source_id, f.title, f.content, f.chunk_id,
                                           s.created_at, s.updated_at, s.meta_json,
                                           bm25(chunks_fts) AS bm25_score
                                    FROM chunks_fts f JOIN sources s ON s.id = (SELECT source_id FROM chunks WHERE id=f.chunk_id)
                                    WHERE chunks_fts MATCH ? ORDER BY bm25_score LIMIT ?""", (match_or, min(limit * 8, 160))).fetchall()
                rows = list(rows) + list(rows2)
            except Exception:
                pass
        # Final fallback when FTS is unavailable or too restrictive.
        if not rows:
            likes = " OR ".join("c.content LIKE ?" for _ in q_tokens[:8])
            params = [f"%{t}%" for t in q_tokens[:8]] + [min(limit * 8, 100)]
            rows = c.execute(f"""SELECT s.source_type, s.source_id, s.title, c.content, c.id AS chunk_id,
                                       s.created_at, s.updated_at, s.meta_json, 0 AS bm25_score
                                FROM chunks c JOIN sources s ON s.id=c.source_id
                                WHERE {likes} LIMIT ?""", params).fetchall()

    # Deduplicate chunks and score locally. Lower BM25 is better, so convert it
    # to a bounded relevance signal and combine with token overlap/freshness.
    seen = set()
    scored = []
    qset = set(q_tokens)
    for r in rows:
        cid = r[4]
        if cid in seen:
            continue
        seen.add(cid)
        content = r[3] or ""
        c_tokens = set(_tokens(content))
        overlap = len(qset & c_tokens) / max(1, len(qset))
        phrase_bonus = 0.22 if q.lower() in content.lower() else 0.0
        bm = float(r[8] or 0.0)
        bm_signal = 1.0 / (1.0 + max(0.0, bm))
        age = _age_days(r[6] or r[5])
        fresh = _freshness(age)
        source_type = r[0] or "local"
        score = (0.50 * overlap + 0.23 * bm_signal + 0.12 * fresh + phrase_bonus) * _source_boost(source_type)
        try:
            meta = json.loads(r[7] or "{}")
        except Exception:
            meta = {}
        scored.append({
            "source_type": source_type,
            "source_id": r[1] or "",
            "title": r[2] or source_type,
            "content": content,
            "chunk_id": cid,
            "created_at": r[5],
            "updated_at": r[6],
            "age_days": round(age, 2),
            "freshness": round(fresh, 3),
            "relevance": round(max(0.0, min(1.0, score)), 4),
            "provenance": meta.get("provenance") or source_type,
            "meta": meta,
        })
    scored.sort(key=lambda x: (x["relevance"], x["freshness"]), reverse=True)
    # Memory 3.0 adds semantic retrieval when Gemini Embedding 2 is available.
    # If embeddings are unavailable, it falls back internally to lexical scoring,
    # so the existing Memory 2.0 search remains fully functional.
    try:
        from .memory3 import search as memory3_search
        semantic_rows = memory3_search(q, limit=max(limit, 8))
        for item in semantic_rows:
            scored.append({
                "source_type": "memory3",
                "source_id": item.get("id", ""),
                "title": "Memoria 3.0 · " + (item.get("category") or "general"),
                "content": item.get("text", ""),
                "chunk_id": "memory3:" + str(item.get("id", "")),
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
                "age_days": item.get("age_days", 0),
                "freshness": max(0.0, 1.0 - min(1.0, float(item.get("age_days", 0)) / 180.0)),
                "relevance": min(1.0, float(item.get("relevance", 0)) * 1.04),
                "provenance": item.get("provenance", "user_explicit"),
                "meta": {
                    "memory_type": item.get("memory_type"),
                    "permanence": item.get("permanence"),
                    "importance": item.get("importance"),
                    "category": item.get("category"),
                    "semantic_score": item.get("semantic_score"),
                },
            })
    except Exception:
        pass
    scored.sort(key=lambda x: (x["relevance"], x.get("freshness", 0)), reverse=True)
    return scored[:limit]


def search(query, limit=10):
    return search_hybrid(query, limit)


def context_for(query, limit=8, max_chars=12000):
    rows = search_hybrid(query, limit)
    out = []
    used = 0
    for r in rows:
        label = r.get("title") or r.get("source_type") or "Memoria"
        freshness = "actual" if r.get("age_days", 9999) <= 1 else f"hace {r.get('age_days', 0):.0f} días"
        piece = f"[{label} · {r.get('source_type')} · {freshness}] {r.get('content','')}"
        if used + len(piece) > max_chars:
            piece = piece[:max(0, max_chars - used)]
        if piece:
            out.append(piece)
            used += len(piece)
        if used >= max_chars:
            break
    return "\n".join(out)


def memory_insights():
    """Compact diagnostics for the Memory 2.0 UI and health panel."""
    with _conn() as c:
        by_type = [dict(r) for r in c.execute(
            "SELECT source_type, COUNT(*) AS sources FROM sources GROUP BY source_type ORDER BY sources DESC"
        ).fetchall()]
        recent = [dict(r) for r in c.execute(
            "SELECT source_type, title, updated_at FROM sources ORDER BY updated_at DESC LIMIT 8"
        ).fetchall()]
    return {"by_type": by_type, "recent": recent}

def stats():
    with _conn() as c:
        sources = c.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        chunks = c.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    return {"sources": sources, "chunks": chunks, "database": str(_db_file())}


def _extract_pdf(path):
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError("Falta pypdf para leer PDFs. Instala las dependencias de Zar.")
    reader = PdfReader(str(path))
    pages = []
    for i, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if text.strip():
            pages.append(f"Página {i+1}: {text}")
    return "\n\n".join(pages)


def _extract_docx(path):
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    return "\n".join(t.text or "" for t in root.findall(".//w:t", ns))


def _extract_pptx(path):
    texts = []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if name.startswith("ppt/slides/slide") and name.endswith(".xml"):
                root = ET.fromstring(z.read(name))
                texts.extend(t.text or "" for t in root.iter() if t.tag.endswith("}t"))
    return "\n".join(texts)


def _extract_xlsx(path):
    # Lectura ligera de hojas: suficiente para indexar texto y poder localizar datos.
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            shared = ["".join(t.text or "" for t in si.iter() if t.tag.endswith("}t")) for si in root]
        texts = []
        for name in z.namelist():
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"):
                root = ET.fromstring(z.read(name))
                for cell in root.iter():
                    if not cell.tag.endswith("}c"):
                        continue
                    typ = cell.attrib.get("t")
                    value = next((x.text for x in cell if x.tag.endswith("}v")), None)
                    if value is None:
                        value = next((x.text for x in cell if x.tag.endswith("}is")), "")
                    if typ == "s" and value and value.isdigit() and int(value) < len(shared):
                        value = shared[int(value)]
                    if value:
                        texts.append(str(value))
        return "\n".join(texts)


def extract_text(path, mime=""):
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".pdf" or mime == "application/pdf":
        return _extract_pdf(path)
    if ext == ".docx":
        return _extract_docx(path)
    if ext == ".pptx":
        return _extract_pptx(path)
    if ext == ".xlsx":
        return _extract_xlsx(path)
    if ext in {".txt", ".md", ".csv", ".json", ".html", ".htm", ".xml", ".py", ".js", ".css"} or (mime or "").startswith("text/"):
        return path.read_text(encoding="utf-8", errors="ignore")
    return ""


def index_file_from_disk(item, path):
    text = extract_text(path, item.get("mime", ""))
    if text.strip():
        return index_file(item, text=text)
    return index_file(item, text=item.get("note", ""))


def bootstrap_from_legacy(memory_items, history_items, conversation_items, file_items):
    """Migra datos JSON antiguos una sola vez al índice persistente."""
    with _conn() as c:
        done = c.execute("SELECT 1 FROM migrations WHERE name='legacy_v1'").fetchone()
        if done:
            return
    for m in memory_items or []:
        try: index_memory(m.get("id") or _hash(m.get("text")), m.get("text", ""))
        except Exception: pass
    for m in history_items or []:
        try: index_message(m.get("role", "user"), m.get("content", ""), _hash(m.get("role"), m.get("content"), m.get("created_at")))
        except Exception: pass
    for m in conversation_items or []:
        try: index_message(m.get("role", "user"), m.get("content", ""), _hash("conversation", m.get("role"), m.get("content"), m.get("created_at")))
        except Exception: pass
    for f in file_items or []:
        try: index_file(f)
        except Exception: pass
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO migrations(name,done_at) VALUES('legacy_v1',?)", (_now(),))
        c.commit()
