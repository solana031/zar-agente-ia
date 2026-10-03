"""ZAR Web Agency: lead discovery, shadcn-inspired demo generation and bounded outreach."""
from __future__ import annotations

import html
import json
import os
import re
import uuid
import requests
from pathlib import Path

from . import holdings
from .maps import maps_search_text
from .jev_decision import gate
from .web_search import public_search_results


def status():
    return {"maps_configured": bool(os.environ.get("ZAR_MAPS_API_KEY","").strip()), "gmail_via_existing_zar_oauth": True, "generator":"ZAR component system · shadcn/ui-inspired", "auto_send_default":False}


def discover(scope_id, query, max_results=10):
    data=maps_search_text(query,max_results=max_results)
    if not data.get("ok"): return data
    leads=[]
    for p in data.get("places") or []:
        if p.get("website"):
            continue
        lead={"id":p.get("id") or uuid.uuid4().hex[:12],"name":p.get("name"),"address":p.get("address"),"phone":p.get("phone"),"maps_url":p.get("maps_url"),"website":p.get("website") or "","rating":p.get("rating"),"reviews":p.get("reviews"),"status":"DISCOVERED"}
        leads.append(lead)
        holdings.queue_task(scope_id,"web_agency","lead",lead,requires_approval=False)
    holdings.update_company(scope_id,"web_agency",action=f"Maps: {len(leads)} negocio(s) sin web detectados para «{query}»",event="DISCOVERY",event_detail=query)
    return {"ok":True,"query":query,"leads":leads}


def _slug(value):
    s=re.sub(r"[^a-z0-9]+","-",str(value or "negocio").lower()).strip("-")
    return (s or "negocio")[:60]+"-"+uuid.uuid4().hex[:6]


def build_demo(scope_id, lead, price_eur=490):
    lead=dict(lead or {}); name=str(lead.get("name") or "Tu negocio"); address=str(lead.get("address") or "Madrid")
    slug=_slug(name); root=Path(os.environ.get("ZAR_DATA_DIR","/data"))/"holdings_public_demos"/slug; root.mkdir(parents=True,exist_ok=True)
    safe_name=html.escape(name); safe_addr=html.escape(address); phone=html.escape(str(lead.get("phone") or ""))
    doc=f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{safe_name}</title><style>:root{{--bg:#09090b;--card:#111113;--fg:#fafafa;--muted:#a1a1aa;--line:#27272a;--accent:#fafafa}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font-family:Inter,ui-sans-serif,system-ui,sans-serif}}.wrap{{max-width:1080px;margin:auto;padding:28px}}nav{{display:flex;justify-content:space-between;align-items:center;padding:12px 0;border-bottom:1px solid var(--line)}}.badge,.btn{{border:1px solid var(--line);border-radius:10px;padding:10px 14px;background:#18181b;color:#fff;text-decoration:none}}.hero{{padding:90px 0 60px;display:grid;grid-template-columns:1.35fr .65fr;gap:34px;align-items:center}}h1{{font-size:clamp(42px,7vw,82px);line-height:.94;letter-spacing:-.055em;margin:0 0 20px}}p{{color:var(--muted);font-size:18px;line-height:1.6}}.card{{border:1px solid var(--line);background:var(--card);border-radius:18px;padding:24px}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:32px 0}}.cta{{display:flex;gap:10px;flex-wrap:wrap}}footer{{border-top:1px solid var(--line);margin-top:60px;padding:30px 0;color:var(--muted)}}@media(max-width:720px){{.hero,.grid{{grid-template-columns:1fr}}.hero{{padding-top:55px}}}}</style></head><body><div class="wrap"><nav><b>{safe_name}</b><span class="badge">Demo profesional</span></nav><section class="hero"><div><div class="badge" style="display:inline-block">{safe_addr}</div><h1>Una presencia digital a la altura de tu negocio.</h1><p>Web rápida, clara, adaptable a móvil y pensada para convertir visitas en llamadas, reservas o clientes.</p><div class="cta"><a class="btn" href="#contacto">Contactar</a><a class="btn" href="#servicios">Ver servicios</a></div></div><div class="card"><b>Información</b><p>{safe_addr}</p><p>{phone or 'Contacto directo y horario del negocio'}</p></div></section><section id="servicios" class="grid"><div class="card"><h3>Diseño premium</h3><p>Jerarquía limpia, componentes consistentes y experiencia móvil.</p></div><div class="card"><h3>Más clientes</h3><p>Llamadas a la acción visibles y contenido orientado a conversión.</p></div><div class="card"><h3>Listo para crecer</h3><p>SEO técnico básico, rendimiento y estructura extensible.</p></div></section><section id="contacto" class="card"><h2>¿Hablamos?</h2><p>Esta es una demo inicial creada para {safe_name}. El contenido final se adapta contigo antes de publicar.</p></section><footer>Demo creada por ZAR Web Agency · Sistema visual inspirado en principios de componentes accesibles tipo shadcn/ui.</footer></div></body></html>'''
    (root/"index.html").write_text(doc,encoding="utf-8")
    result={"slug":slug,"relative_url":f"/holdings/demo/{slug}/","price_eur":float(price_eur),"lead":lead}
    holdings.update_company(scope_id,"web_agency",action=f"Demo creada para {name}",event="DEMO",event_detail=f"{name} · {price_eur:.0f} EUR")
    return result


def prepare_outreach(scope_id, lead, demo_url, price_eur=490):
    lead=dict(lead or {}); name=lead.get("name") or "tu negocio"
    decision=gate("Preparar contacto comercial por email",{"business":lead,"price_eur":price_eur,"demo_url":demo_url},"medium")
    subject=f"He preparado una propuesta web para {name}"
    body=(f"Hola,\n\nHe visto {name} y he preparado una demo web específica para vuestro negocio: {demo_url}\n\n"
          f"La propuesta completa tendría un precio orientativo de {float(price_eur):.0f} € e incluiría adaptación móvil, diseño, contenido inicial y puesta en marcha. "
          "Si os interesa, puedo enseñaros la demo y ajustar el alcance antes de cualquier compromiso.\n\n"
          "Si preferís que no vuelva a contactar, decídmelo y no enviaré más mensajes.\n\nUn saludo")
    return {"ok":True,"subject":subject,"body":body,"decision":decision,"send_authority":False,"note":"Usa el flujo Gmail de ZAR para revisar y confirmar el envío."}


def negotiate(current_price, customer_message, floor_price=350, max_discount_pct=15):
    current=float(current_price); floor=float(floor_price); max_discount=float(max_discount_pct)
    decision=gate("Responder a negociación comercial",{"current_price":current,"floor":floor,"max_discount_pct":max_discount,"message":customer_message},"medium")
    lowest=max(floor,round(current*(1-max_discount/100),2))
    offered=max(lowest,round((current+lowest)/2,2))
    return {"decision":decision,"current_price":current,"floor_price":floor,"suggested_offer":offered,"requires_human_review":decision["requires_review"],"send_authority":False}


_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)

def find_contact_email(lead):
    """Find public contact-email candidates without sending anything."""
    lead=dict(lead or {})
    name=str(lead.get("name") or "").strip(); address=str(lead.get("address") or "").strip()
    if not name: raise ValueError("Falta el negocio.")
    result=public_search_results(f'"{name}" {address} email contacto', limit=8)
    emails=[]; sources=[]
    if result.get("ok"):
        for row in result.get("results") or []:
            blob=" ".join(str(row.get(k) or "") for k in ("title","snippet","url"))
            for email in _EMAIL_RE.findall(blob):
                low=email.lower()
                if any(x in low for x in ("example.com","sentry.io","wixpress.com","cloudflare.com","wordpress.com")):
                    continue
                if email not in emails: emails.append(email)
            if row.get("url"): sources.append(row.get("url"))
    return {"ok":True,"emails":emails[:8],"sources":sources[:8],"verified":False,"note":"Candidatos encontrados en fuentes públicas; revisar antes de usar."}


def create_outreach_draft(scope_id, lead, demo_url, email, price_eur=490):
    email=str(email or "").strip()
    if not _EMAIL_RE.fullmatch(email): raise ValueError("Email no válido.")
    prepared=prepare_outreach(scope_id, lead, demo_url, price_eur)
    decision=prepared.get("decision") or {}
    if decision.get("allowed") is False:
        raise RuntimeError("Jev/política ha bloqueado esta propuesta de outreach.")
    from .gmail import create_draft
    saved=create_draft(email, prepared["subject"], prepared["body"])
    holdings.update_company(scope_id,"web_agency",action=f"Borrador Gmail preparado para {lead.get('name') or email}; no enviado.",event="OUTREACH_DRAFT",event_detail=email)
    return {"ok":True,"draft_id":saved.get("id"),"email":email,"subject":prepared["subject"],"sent":False,"decision":decision}
