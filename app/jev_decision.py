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

def evaluate(scope_id, context):
    """Typed server policy judgment. It never grants execution authority."""
    from . import holdings
    import uuid
    action=str(context.get('action') or '')
    denied=action in {'TRADING_LIVE','LIVE_TRADE'} or bool(holdings.read(scope_id).get('global_stop'))
    external=action in {'SEND_EMAIL','MEDIA_PUBLISH','BUY_DOMAIN','PAYMENT'}
    decision='DENY' if denied else 'CONFIRM' if external else 'ALLOW'
    row={'id':uuid.uuid4().hex,'timestamp':holdings._now(),'task_id':context.get('task_id'),'requesting_agent':context.get('agent','TaskOrchestrator'),'decision':decision,'subsequent_state':'PENDING',
         'output':{'decision':decision,'confidence':1.0,'risk':'HIGH' if external or denied else 'LOW','risk_score':1 if denied else .7 if external else .1,'reason':'STOP GLOBAL o Live bloqueado.' if denied else 'Requiere revisión y confirmación separada.' if external else 'Paso interno autorizado por el plan.','reasoning':'Política aplicada por el servidor.','cost':context.get('cost'),'policy':'ZAR_SERVER_POLICY','constraints':['EXPLICIT_CONFIRMATION'] if external else [],'execution_authority':False,'source':'ZAR policy','provider_state':'LOCAL'}}
    with holdings.transaction(scope_id):
        state=holdings.read(scope_id);state.setdefault('jev_decisions',[]).append(row);holdings.write(scope_id,state)
    return dict(row['output'],id=row['id'],timestamp=row['timestamp'])


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


def proposal(scope_id, data, *, use_provider=False):
    """Audited typed business judgment. Policy, never the model, owns authority."""
    from . import holdings
    from decimal import Decimal
    import uuid
    if not isinstance(data, dict):
        raise ValueError('Propuesta estructurada requerida.')
    allowed = {'source_agent', 'task', 'task_id', 'wallet_id', 'expected_cost', 'expected_revenue',
               'currency', 'risk', 'urgency', 'resources', 'suggested_provider', 'suggested_model', 'action'}
    if set(data) - allowed:
        raise ValueError('Campos no admitidos en la propuesta.')
    p = {key: data.get(key) for key in allowed}
    for field in ('source_agent', 'task', 'action'):
        if not isinstance(p[field], str) or not p[field].strip() or len(p[field]) > 2000:
            raise ValueError('Agente, tarea y acción requeridos; máximo 2000 caracteres.')
    for field in ('expected_cost', 'expected_revenue'):
        if p[field] is not None:
            v = Decimal(str(p[field]))
            if not v.is_finite() or v < 0:
                raise ValueError('Importes finitos y no negativos requeridos.')
            p[field] = str(v)
    for field in ('risk', 'urgency'):
        if p[field] is not None:
            if isinstance(p[field], bool) or not isinstance(p[field], (int, float)) or not math.isfinite(p[field]) or not 0 <= p[field] <= 1:
                raise ValueError('Riesgo/urgencia entre 0 y 1 o null.')
    if p['currency'] is not None and not re.fullmatch(r'[A-Z]{3}', str(p['currency'])):
        raise ValueError('Moneda ISO requerida.')
    if p['resources'] is None:
        p['resources'] = []
    if not isinstance(p['resources'], list) or len(p['resources']) > 30 or any(not isinstance(x, str) or len(x) > 120 for x in p['resources']):
        raise ValueError('Recursos: lista de nombres de capacidades.')
    for field in ('suggested_provider', 'suggested_model', 'task_id', 'wallet_id'):
        if p[field] is not None and (not isinstance(p[field], str) or len(p[field]) > 150):
            raise ValueError('Referencia inválida.')
    financial = (p['expected_cost'] is not None and Decimal(p['expected_cost']) > 0) or bool(
        re.search(r'compr|paga|gasta|transfer|purchase|spend|payment|publish|publica|send|envi', p['action'], re.I))
    local = bool(p['resources']) and set(p['resources']) <= {'local_read','local_write'} and p['expected_cost'] is not None and Decimal(p['expected_cost']) == 0
    judgment, reason = ('APPROVE', 'Operación local sin autoridad económica.') if local else ('DEFER', 'Faltan recursos/proveedor verificados; preparar y revisar.')
    risk = p['risk']
    if financial:
        judgment, reason = 'ESCALATE', 'Acción económica/externa: requiere aprobación explícita vinculada a la operación.'
    elif risk is None or p['expected_cost'] is None:
        judgment, reason = 'DEFER', 'Coste o riesgo desconocido; completar datos antes de ejecutar.'
    if risk is not None and risk >= .8:
        judgment, reason = 'REJECT', 'Riesgo declarado por encima del umbral permitido.'
    confidence = None
    provider_state = 'POR CONFIGURAR' if not _key() else 'NO DISPONIBLE'
    provider_source = 'ZAR policy'
    if use_provider:
        remote = decide(p, {'route': {'type':'choice', 'instructions':'Decide la propuesta; nunca autoriza pagos/publicación.',
            'criteria': {x:x for x in ('APPROVE','REJECT','DEFER','ESCALATE')}}})
        if not remote.get('fallback') and remote.get('state') == 'ONLINE':
            answer = remote['answers']['route']
            candidate = answer['choice']
            # Provider may only make local policy stricter, never unlock economics.
            if candidate in {'REJECT', 'DEFER', 'ESCALATE'} and judgment != 'REJECT':
                judgment, reason = candidate, 'JEV recomienda '+candidate+'; se conservan los guardrails del servidor.'
            c = answer.get('confidence')
            confidence = c if isinstance(c, (int,float)) and not isinstance(c,bool) and math.isfinite(c) and 0 <= c <= 1 else None
            provider_state, provider_source = 'LISTO', 'TypeSafe Jev'
        else:
            provider_state = 'ERROR' if _key() else 'POR CONFIGURAR'
            if judgment == 'APPROVE' and not local:
                judgment, reason = 'DEFER', 'Proveedor no disponible.'
    profit = None if p['expected_cost'] is None or p['expected_revenue'] is None else str(Decimal(p['expected_revenue'])-Decimal(p['expected_cost']))
    output = {'decision': judgment, 'confidence': confidence, 'reasoning': reason, 'risk_score': risk,
        'expected_cost': p['expected_cost'], 'expected_revenue': p['expected_revenue'], 'expected_profit': profit,
        'currency': p['currency'], 'priority': p['urgency'], 'recommended_agent': p['source_agent'],
        'recommended_provider': p['suggested_provider'], 'next_action': 'EXECUTE_LOCAL_OPERATION' if judgment == 'APPROVE' and local else 'HUMAN_REVIEW' if judgment == 'ESCALATE' else 'COMPLETE_INPUT' if judgment == 'DEFER' else 'STOP',
        'source': provider_source, 'provider_state': provider_state, 'execution_authority': False}
    row = {'id': uuid.uuid4().hex, 'timestamp': holdings._now(), 'input': p, 'output': output,
           'requesting_agent': p['source_agent'], 'decision': judgment, 'subsequent_state': 'PENDING',
           'task_id': p['task_id'], 'wallet_id': p['wallet_id']}
    with holdings.transaction(scope_id):
        state = holdings.read(scope_id)
        state.setdefault('jev_decisions', []).append(row)
        if use_provider:
            from .business_connectors import verification
            state.setdefault('verified_connectors', {})['JEV'] = verification('JEV',provider_state,'validated decision response')
        holdings.write(scope_id, state)
    return row


def decision_state(scope_id, decision_id, state):
    from . import holdings
    with holdings.transaction(scope_id):
        data = holdings.read(scope_id)
        row = next(x for x in data.get('jev_decisions', []) if x['id'] == decision_id)
        row['subsequent_state'] = str(state)[:80]
        holdings.write(scope_id, data)
