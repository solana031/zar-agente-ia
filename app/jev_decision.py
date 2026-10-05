"""Optional Jev / TypeSafe decision layer for ZAR.

The hosted Jev model is used when JEV_API_KEY or TYPESAFE_API_KEY is present.
Without a key ZAR keeps working through a conservative deterministic fallback.
The decision layer never executes tools: it only returns typed judgments.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from datetime import datetime, timezone

import requests

BASE = os.environ.get("JEV_API_BASE", "https://api.typesafe.ai").rstrip("/")
MODEL = os.environ.get("JEV_MODEL", "jev-latest")


def _key():
    return (os.environ.get("JEV_API_KEY") or os.environ.get("TYPESAFE_API_KEY") or "").strip()


def status():
    return {"configured": bool(_key()), "state": "CONFIGURED_UNVERIFIED" if _key() else "NOT_CONFIGURED", "provider": "TypeSafe Jev" if _key() else "ZAR deterministic fallback", "model": MODEL, "base": BASE, "execution_authority": False}


def _validated(data, questions):
    if not isinstance(data, dict) or not isinstance(data.get('answers'), dict):
        raise ValueError('Invalid Jev response')
    for qid, question in questions.items():
        answer = data['answers'].get(qid)
        kind = question.get('type', 'noul')
        if not isinstance(answer, dict) or answer.get('type') != kind:
            raise ValueError('Missing or mismatched Jev answer')
        if kind == 'choice':
            choice = answer.get('choice')
            if not isinstance(choice, str) or choice not in question.get('criteria', {}):
                raise ValueError('Unknown Jev choice')
        else:
            value = answer.get(kind)
            maximum = 1 if kind == 'noul' else max(0, len(question.get('criteria', [])) - 1)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= maximum or not math.isfinite(value):
                raise ValueError('Invalid Jev numeric answer')
    return data


def _fallback(state, questions):
    text = json.dumps(state, ensure_ascii=False).lower() if not isinstance(state, str) else state.lower()
    answers = {}
    risk_words = ("delete", "borrar", "pagar", "payment", "comprar", "buy", "publish", "publicar", "send", "enviar", "live", "credential", "secret", "contraseña")
    risky = any(w in text for w in risk_words)
    for qid, q in (questions or {}).items():
        typ = str((q or {}).get("type") or "noul").lower()
        instructions = str((q or {}).get("instructions") or "").lower()
        if typ == "choice":
            criteria = (q or {}).get("criteria") or {}
            keys = list(criteria) if isinstance(criteria, dict) else []
            if not keys:
                answers[qid] = {"type": "choice", "choice": None, "probabilities": {}, "confidence": 0.0}
                continue
            selected = keys[0]
            for key in keys:
                k = str(key).lower()
                if k in text or k in instructions:
                    selected = key; break
            prob = {str(k): round((0.72 if k == selected else 0.28 / max(1, len(keys)-1)), 4) for k in keys}
            answers[qid] = {"type":"choice","choice":selected,"probabilities":prob,"confidence":0.55,"fallback":True}
        elif typ == "score":
            criteria = (q or {}).get("criteria") or []
            n = len(criteria) if isinstance(criteria, list) else len(criteria or {})
            score = float(max(0, n-1 if risky else min(1, max(0, n-1))))
            answers[qid] = {"type":"score","score":score,"confidence":0.45,"fallback":True}
        else:
            yes = risky or any(x in instructions for x in ("human", "humano", "review", "revisión", "riesgo")) and risky
            answers[qid] = {"type":"noul","noul":0.9 if yes else 0.15,"fallback":True}
    return {"model":"zar-deterministic-fallback","answers":answers,"usage":{"input_tokens":0,"output_tokens":0},"fallback":True,"state":"NOT_CONFIGURED"}


def decide(state, questions, timeout=10):
    key = _key()
    if not key:
        return _fallback(state, questions)
    payload = {"model": MODEL, "state": state, "questions": questions}
    last = None
    for attempt in range(2):
        try:
            r = requests.post(
                BASE + "/v1/systemone",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload, timeout=timeout, allow_redirects=False,
            )
            if r.ok:
                data = _validated(r.json(), questions); data["fallback"] = False; data['state'] = 'ONLINE'; return data
            last = RuntimeError(f"Jev HTTP {r.status_code}")
            if r.status_code not in {429,500,502,503,504}: break
        except (requests.RequestException, ValueError) as exc:
            last = RuntimeError(type(exc).__name__)
        time.sleep(0.4)
    result = _fallback(state, questions)
    result['state'] = 'DEGRADED'
    result["provider_error"] = str(last)[:500] if last else "Jev no disponible"
    return result


def gate(action, state=None, risk_hint="medium"):
    state_obj = {"action": action, "risk_hint": risk_hint, "context": state or {}}
    result = decide(state_obj, {
        "risk": {"type":"score","instructions":"Valora el riesgo operacional de ejecutar esta acción.","criteria":["bajo","medio","alto","crítico"]},
        "human_review": {"type":"noul","instructions":"¿Esta acción debería requerir revisión humana antes de ejecutarse?"},
        "route": {"type":"choice","instructions":"Selecciona el siguiente paso seguro.","criteria":{"allow":"Puede continuar","review":"Requiere revisión humana","deny":"Debe bloquearse"}},
    })
    a = result.get("answers") or {}
    review_prob = float((a.get("human_review") or {}).get("noul") or 0.0)
    route = (a.get("route") or {}).get("choice") or "review"
    risk = float((a.get("risk") or {}).get("score") or 0.0)
    # Code owns policy. Jev only supplies judgments.
    requires_review = route != "allow" or review_prob >= 0.55 or risk >= 2.0
    return {
        "allowed": route != "deny",
        "requires_review": requires_review,
        "route": route,
        "review_probability": round(review_prob, 4),
        "risk_score": risk,
        "decision": result,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
