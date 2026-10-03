"""Deterministic zero-token AI brain router for ZAR.

The router never calls an LLM to decide which LLM to call. It uses cheap local
heuristics plus provider availability, so routing itself costs zero API tokens.
"""
from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass, asdict
from typing import Dict, List

import requests

_LOCK = threading.Lock()
_LAST_DECISION: Dict[str, object] = {}
_LOCAL_CACHE = {"at": 0.0, "ok": False, "models": []}


def _env(name: str, default: str) -> str:
    return (os.environ.get(name) or default).strip()


@dataclass(frozen=True)
class BrainRoute:
    tier: str
    provider: str
    model: str
    reason: str
    fallback_tier: str = "balanced"

    def public(self):
        return asdict(self)


def brain_models() -> Dict[str, Dict[str, str]]:
    return {
        "local": {"provider": "local", "model": _env("OLLAMA_MODEL", "qwen3:8b")},
        "economy": {"provider": "gemini", "model": _env("ZAR_GEMINI_ECONOMY_MODEL", "gemini-3.5-flash-lite")},
        "balanced": {"provider": "gemini", "model": _env("ZAR_GEMINI_BALANCED_MODEL", "gemini-3.8-flash")},
        "strong": {"provider": "openai", "model": _env("ZAR_OPENAI_STRONG_MODEL", "gpt-5.6-terra")},
        "max": {"provider": "openai", "model": _env("ZAR_OPENAI_MAX_MODEL", "gpt-5.6-sol")},
        "openai_economy": {"provider": "openai", "model": _env("ZAR_OPENAI_ECONOMY_MODEL", "gpt-5.6-luna")},
    }


def local_available(cfg, force: bool = False) -> bool:
    """True only when Ollama is reachable from the ZAR backend itself."""
    now = time.monotonic()
    ttl = float(_env("ZAR_LOCAL_PROBE_TTL", "20"))
    with _LOCK:
        if not force and now - float(_LOCAL_CACHE["at"]) < ttl:
            return bool(_LOCAL_CACHE["ok"])
    base = (cfg.get("local") or {}).get("base_url", "http://127.0.0.1:11434").rstrip("/")
    wanted = (cfg.get("local") or {}).get("model", "qwen3:8b")
    ok = False
    names: List[str] = []
    try:
        r = requests.get(base + "/api/tags", timeout=0.8)
        if r.ok:
            names = [str(x.get("name", "")) for x in r.json().get("models", [])]
            ok = bool(names) and (wanted in names or any(n.split(":", 1)[0] == wanted.split(":", 1)[0] for n in names))
    except requests.RequestException:
        ok = False
    with _LOCK:
        _LOCAL_CACHE.update({"at": now, "ok": ok, "models": names})
    return ok


def _contains(text: str, patterns: List[str]) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def choose_brain(message: str, cfg) -> BrainRoute:
    """Classify a request without spending LLM tokens."""
    text = (message or "").strip()
    low = text.lower()
    models = brain_models()

    # Optional Jev System-One routing. It never removes the deterministic path:
    # network/auth/model failures fall straight through to the legacy zero-token router.
    if (os.environ.get("JEV_API_KEY") or os.environ.get("TYPESAFE_API_KEY")) and str(os.environ.get("ZAR_JEV_ROUTER", "1")).lower() not in {"0","false","off","no"}:
        try:
            from .jev_decision import decide
            j = decide({"message": text[:6000], "length": len(text)}, {
                "tier": {"type":"choice","instructions":"Elige el nivel mínimo de cerebro que pueda resolver bien esta petición.","criteria": {
                    "economy":"conversación y tareas sencillas", "balanced":"herramientas o complejidad media",
                    "strong":"código, análisis o planificación compleja", "max":"auditoría o razonamiento largo/de máxima exigencia"}},
                "human_review": {"type":"noul","instructions":"¿La tarea implica una acción sensible que debería mantener confirmación humana?"}
            }, timeout=3)
            ans=j.get("answers") or {}; tier=(ans.get("tier") or {}).get("choice")
            if tier in {"economy","balanced","strong","max"}:
                item=models[tier]
                return BrainRoute(tier, item["provider"], item["model"], f"Jev Decision Layer · {tier}")
        except Exception:
            pass

    # Explicit overrides are useful for testing and expert users.
    if _contains(low, [r"\b(usa|utiliza)\s+(el\s+)?(pc|ollama|modelo local|cerebro local)\b"]):
        if local_available(cfg):
            return BrainRoute("local", "local", (cfg.get("local") or {}).get("model", models["local"]["model"]), "Petición explícita de cerebro local")
    if _contains(low, [r"\b(usa|utiliza)\s+gpt\b", r"\bchatgpt\b"]):
        return BrainRoute("strong", "openai", models["strong"]["model"], "Petición explícita de GPT")
    if _contains(low, [r"\b(usa|utiliza)\s+gemini\b"]):
        return BrainRoute("balanced", "gemini", models["balanced"]["model"], "Petición explícita de Gemini")

    # High-stakes/long-horizon reasoning gets the strongest configured brain.
    max_patterns = [
        r"\b(audita|auditor[ií]a|arquitectura completa|investigaci[oó]n profunda|razona a fondo)\b",
        r"\b(debug|depura|refactoriza)\b.{0,80}\b(complej|proyecto|repositorio|arquitectura)\b",
        r"\b(plan|estrategia)\b.{0,80}\b(detallad|complet|multi.?paso|largo plazo)\b",
    ]
    if len(text) > 6000 or _contains(low, max_patterns):
        return BrainRoute("max", "openai", models["max"]["model"], "Razonamiento largo o de máxima exigencia")

    strong_patterns = [
        r"\b(c[oó]digo|programa|python|javascript|typescript|sql|api|backend|frontend|github|railway)\b",
        r"\b(analiza|compara|diagnostica|diseña|optimiza|planifica)\b",
        r"\b(contrato|legal|fiscal|finanzas|inversi[oó]n|m[eé]dic|salud)\b",
        r"\b(varios pasos|paso a paso|profundamente|en detalle)\b",
    ]
    if len(text) > 2200 or _contains(low, strong_patterns):
        return BrainRoute("strong", "openai", models["strong"]["model"], "Tarea compleja de análisis, código o planificación")

    # Tool/current-data requests benefit from the proven Gemini agent/tool path.
    tool_patterns = [
        r"\b(gmail|correo|calendar|calendario|drive|docs|sheets|slides|forms|contactos|youtube)\b",
        r"\b(busca|internet|web|actual|hoy|ahora|noticias|tiempo|mapa|archivo|pdf)\b",
        r"\b(crea|env[ií]a|guarda|edita|modifica|elimina|publica|programa)\b",
    ]
    if len(text) > 900 or _contains(low, tool_patterns):
        return BrainRoute("balanced", "gemini", models["balanced"]["model"], "Herramientas, contexto o complejidad media")

    # Local wins for lightweight language tasks only when it is genuinely reachable.
    local_patterns = [
        r"\b(resume|resumir|reescribe|reformula|corrige|traduce|clasifica|extrae|lista|ideas?)\b",
        r"\b(qu[eé] significa|expl[ií]came|define)\b",
    ]
    local_max = int(_env("ZAR_AUTO_LOCAL_MAX_CHARS", "900"))
    if len(text) <= local_max and _contains(low, local_patterns) and local_available(cfg):
        return BrainRoute("local", "local", (cfg.get("local") or {}).get("model", models["local"]["model"]), "Tarea ligera resoluble sin tokens externos")

    return BrainRoute("economy", "gemini", models["economy"]["model"], "Conversación o tarea cotidiana de bajo coste")


def remember_decision(route: BrainRoute, actual_provider: str | None = None, actual_model: str | None = None):
    with _LOCK:
        _LAST_DECISION.clear()
        _LAST_DECISION.update({
            **route.public(),
            "actual_provider": actual_provider or route.provider,
            "actual_model": actual_model or route.model,
            "at": time.time(),
        })


def last_decision():
    with _LOCK:
        return dict(_LAST_DECISION)


def catalog(cfg):
    rows = []
    for tier, item in brain_models().items():
        if tier == "openai_economy":
            continue
        rows.append({"tier": tier, **item})
    return {
        "mode": "auto",
        "routing_cost_tokens": 0,
        "local_reachable": local_available(cfg),
        "brains": rows,
        "last": last_decision(),
    }
