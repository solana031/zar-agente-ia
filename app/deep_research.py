"""ZAR v30.1.2 — Deep Research router and archive.

Uses Google's Interactions API because Gemini Deep Research is exposed there and
requires background execution for long-running research tasks.
"""
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

from .model_router import model_for
from .user_scope import get_current_user, safe_slug


INTERACTIONS_URL = os.environ.get(
    "ZAR_GEMINI_INTERACTIONS_URL",
    "https://generativelanguage.googleapis.com/v1beta/interactions",
).rstrip("/")


def _api_key():
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    try:
        from .config import load
        cfg = load()
        return str(cfg.get("api", {}).get("api_key", "") or "").strip()
    except Exception:
        return ""


def _research_dir():
    root = Path(os.environ.get("ZAR_DATA_DIR", "/data"))
    path = root / "users" / safe_slug() / "research"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _headers(key):
    return {"Content-Type": "application/json", "x-goog-api-key": key}


def is_deep_research_request(message):
    """Conservative router: reserve Deep Research for genuinely multi-step work."""
    t = re.sub(r"\s+", " ", (message or "").strip().lower())
    if not t:
        return False
    strong = (
        r"\binvestiga(?:ción|r)?\b.{0,100}\b(a fondo|profunda|exhaustiv|completa|detallada|mercado|competencia|fuentes|informe|estudio)\b",
        r"\bhaz(?:me)?\s+(?:una\s+)?investigaci[oó]n\b",
        r"\brealiza(?:r)?\s+(?:una\s+)?investigaci[oó]n\b",
        r"\binforme\s+(?:completo|exhaustivo|detallado|profundo)\b",
        r"\ban[aá]lisis\s+(?:exhaustivo|completo|profundo|comparativo)\b",
        r"\bestudio\s+(?:de\s+mercado|completo|exhaustivo|comparativo)\b",
        r"\bdeep\s+research\b",
        r"\bdue\s+diligence\b",
        r"\binvestiga\s+.*\s+y\s+compara\b",
    )
    if any(re.search(p, t, re.I) for p in strong):
        return True
    # Long research-style requests with explicit research verbs.
    return len(t) >= 90 and bool(re.search(r"\b(investiga|investigar|estudia|analiza|compara)\b", t)) and bool(
        re.search(r"\b(fuentes|mercado|competidores|alternativas|tendencias|precios|evidencia|informe)\b", t)
    )


def start_research(query, instructions=""):
    key = _api_key()
    if not key:
        raise RuntimeError("Falta GEMINI_API_KEY para activar Deep Research.")
    query = (query or "").strip()
    if not query:
        raise ValueError("La investigación está vacía.")

    prompt = (
        "Investiga esta petición en profundidad y devuelve un informe en español. "
        "Usa búsqueda web y contrasta las fuentes. Prioriza fuentes primarias, oficiales y fiables. "
        "Distingue hechos, datos, estimaciones y opiniones. Incluye citas o enlaces de las fuentes "
        "que sustentan las afirmaciones importantes. No inventes datos ni fuentes. "
        "Organiza el resultado con resumen ejecutivo, hallazgos, comparación cuando proceda, "
        "incertidumbres/limitaciones y fuentes.\n\nPETICIÓN DEL USUARIO:\n" + query
    )
    if instructions:
        prompt += "\n\nINSTRUCCIONES ADICIONALES:\n" + instructions.strip()

    payload = {
        "agent": model_for("deep_research"),
        "input": prompt,
        "agent_config": {
            "type": "deep-research",
            "thinking_summaries": "auto",
            "collaborative_planning": False,
        },
        "tools": [
            {"type": "google_search"},
            {"type": "url_context"},
        ],
        "background": True,
        "store": True,
    }
    try:
        r = requests.post(INTERACTIONS_URL, headers=_headers(key), json=payload, timeout=60)
    except requests.RequestException as exc:
        raise RuntimeError(f"No se pudo iniciar Deep Research: {exc}") from exc
    if not r.ok:
        raise RuntimeError(f"Deep Research HTTP {r.status_code}: {r.text[:1200]}")
    data = r.json()
    interaction_id = data.get("id") or data.get("interaction_id")
    if not interaction_id:
        raise RuntimeError("Deep Research no devolvió un ID de interacción.")
    return {
        "id": interaction_id,
        "model": model_for("deep_research"),
        "status": data.get("status", "in_progress"),
        "query": query,
    }


def get_research(interaction_id):
    key = _api_key()
    if not key:
        raise RuntimeError("Falta GEMINI_API_KEY para consultar Deep Research.")
    try:
        r = requests.get(
            f"{INTERACTIONS_URL}/{interaction_id}",
            headers={"x-goog-api-key": key},
            timeout=45,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"No se pudo consultar Deep Research: {exc}") from exc
    if not r.ok:
        raise RuntimeError(f"Deep Research HTTP {r.status_code}: {r.text[:1200]}")
    return r.json()


def _text_from_content(content):
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("text"):
                parts.append(str(item["text"]))
        return "\n".join(x for x in parts if x).strip()
    if isinstance(content, dict):
        return str(content.get("text") or "").strip()
    return ""


def extract_report(data):
    """Handle the output shapes used by Interactions/Deep Research responses."""
    for key in ("output_text", "text"):
        text = _text_from_content(data.get(key))
        if text:
            return text
    output = data.get("output")
    text = _text_from_content(output)
    if text:
        return text

    steps = data.get("steps") or []
    candidates = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        for key in ("output_text", "text"):
            text = _text_from_content(step.get(key))
            if text:
                candidates.append(text)
        text = _text_from_content(step.get("content"))
        if text:
            candidates.append(text)
    # Prefer the latest substantial text block; earlier blocks may be progress notes.
    candidates = [x for x in candidates if x.strip()]
    if candidates:
        return max(candidates[-8:], key=len)
    return ""


def wait_for_research(interaction_id, poll_seconds=5, max_seconds=3300):
    started = time.time()
    last = None
    while time.time() - started < max_seconds:
        data = get_research(interaction_id)
        last = data
        status = str(data.get("status") or "").lower()
        if status in {"completed", "failed", "cancelled", "canceled"}:
            report = extract_report(data)
            if status != "completed":
                err = data.get("error") or data.get("failure") or "La investigación no pudo completarse."
                raise RuntimeError(str(err))
            if not report:
                raise RuntimeError("Deep Research terminó pero no devolvió un informe legible.")
            return data, report
        time.sleep(max(2, poll_seconds))
    raise TimeoutError("Deep Research ha superado el tiempo máximo de espera de ZAR.")


def save_report(query, report, interaction_id, model=None):
    report_id = uuid.uuid4().hex
    payload = {
        "id": report_id,
        "user_id": get_current_user(),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "query": query,
        "report": report,
        "interaction_id": interaction_id,
        "model": model or model_for("deep_research"),
    }
    path = _research_dir() / f"{report_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def list_reports(limit=30):
    rows = []
    for path in sorted(_research_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[: max(1, min(int(limit), 100))]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            rows.append({k: data.get(k) for k in ("id", "created_at", "query", "model")})
        except Exception:
            continue
    return rows


def get_report(report_id):
    rid = re.sub(r"[^a-zA-Z0-9_-]", "", str(report_id or ""))
    if not rid:
        return None
    path = _research_dir() / f"{rid}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
