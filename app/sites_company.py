"""ZAR Sites: content-site studio + bounded ad monetisation + reinvestment.

The company can create/search/deploy sites and measure verified AdSense payments.
It never generates artificial traffic/clicks and never buys a domain unless there is
sufficient realised Sites profit, a registrar is configured, and the spend policy
explicitly permits it.
"""
from __future__ import annotations

import base64
import html
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

from . import holdings
from .jev_decision import gate
from .user_scope import safe_slug
from .web_search import public_search_results

_MAX_SITES = 80


def _now():
    return datetime.now(timezone.utc).isoformat()


def _publisher_id():
    raw = (os.environ.get("GOOGLE_ADSENSE_PUBLISHER_ID") or os.environ.get("ADSENSE_PUBLISHER_ID") or "").strip()
    raw = raw.replace("ca-pub-", "pub-")
    if raw and not raw.startswith("pub-") and raw.isdigit():
        raw = "pub-" + raw
    return raw


def _adsense_client():
    pub = _publisher_id()
    return "ca-" + pub if pub.startswith("pub-") else ""


def _root(scope_id):
    p = Path(os.environ.get("ZAR_DATA_DIR", "/data")) / "users" / safe_slug(scope_id) / "holdings" / "sites"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _registry_file(scope_id):
    return _root(scope_id) / "registry.json"


def _public_root():
    p = Path(os.environ.get("ZAR_DATA_DIR", "/data")) / "holdings_public_sites"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _read_registry(scope_id):
    try:
        data = json.loads(_registry_file(scope_id).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _write_registry(scope_id, rows):
    rows = list(rows or [])[-_MAX_SITES:]
    p = _registry_file(scope_id)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)
    return rows


def _slug(value):
    s = re.sub(r"[^a-z0-9]+", "-", str(value or "site").lower()).strip("-")
    return (s or "site")[:54] + "-" + uuid.uuid4().hex[:6]


def status():
    return {
        "adsense_publisher_configured": bool(_publisher_id()),
        "adsense_reporting_configured": bool(os.environ.get("GOOGLE_ADSENSE_ACCESS_TOKEN", "").strip()),
        "adsense_account": os.environ.get("GOOGLE_ADSENSE_ACCOUNT", "").strip(),
        "vercel_configured": bool(os.environ.get("VERCEL_TOKEN", "").strip()),
        "vercel_team_configured": bool(os.environ.get("VERCEL_TEAM_ID", "").strip()),
        "domain_registrant_configured": bool(os.environ.get("ZAR_DOMAIN_REGISTRANT_JSON", "").strip()),
        "organic_growth_only": True,
        "auto_domain_spend_default": False,
        "note": "AdSense requiere que cada sitio/dominio sea aprobado. ZAR no genera tráfico ni clics artificiales.",
    }


def list_sites(scope_id):
    return list(reversed(_read_registry(scope_id)))


def scout_ideas(seed, limit=6):
    seed = str(seed or "ideas útiles España").strip()
    res = public_search_results(f"{seed} tendencias preguntas guía 2026", limit=max(6, int(limit or 6)))
    ideas = []
    for i, row in enumerate((res.get("results") or [])[: max(1, int(limit or 6))]):
        title = re.sub(r"\s+", " ", str(row.get("title") or seed)).strip()
        ideas.append({
            "topic": title[:150],
            "source": row.get("url") or "",
            "snippet": re.sub(r"\s+", " ", str(row.get("snippet") or "")).strip()[:500],
            "score": max(35, 92 - i * 7),
            "strategy": "SEO + utilidad + distribución orgánica",
        })
    if not ideas:
        ideas = [{"topic": seed, "source": "", "snippet": "", "score": 50, "strategy": "SEO + utilidad"}]
    return {"ok": True, "query": seed, "provider": res.get("provider"), "ideas": ideas, "artificial_traffic": False}


def _article_from_sources(topic, rows):
    sections = []
    for row in rows[:6]:
        title = re.sub(r"\s+", " ", str(row.get("title") or "Fuente")).strip()
        snippet = re.sub(r"\s+", " ", str(row.get("snippet") or "")).strip()
        url = str(row.get("url") or "").strip()
        if not title and not snippet:
            continue
        sections.append({"heading": title[:150], "text": snippet[:900], "url": url})
    if not sections:
        sections = [
            {"heading": f"Qué debes saber sobre {topic}", "text": "Guía práctica creada por ZAR Sites. Añade fuentes y ejemplos propios para ampliar este contenido.", "url": ""},
            {"heading": "Cómo aplicarlo", "text": "Prioriza información útil, comprobable y fácil de actualizar. Evita contenido duplicado o creado únicamente para anuncios.", "url": ""},
        ]
    return sections


def build_site(scope_id, topic, name="", *, queue_promotion=True):
    topic = re.sub(r"\s+", " ", str(topic or "")).strip()
    if not topic:
        raise ValueError("Falta el tema del sitio.")
    display = re.sub(r"\s+", " ", str(name or topic)).strip()[:100]
    slug = _slug(display)
    root = _public_root() / slug
    root.mkdir(parents=True, exist_ok=True)
    search = public_search_results(f"{topic} guía datos preguntas", limit=8)
    rows = search.get("results") or []
    sections = _article_from_sources(topic, rows)
    pub = _publisher_id(); client = _adsense_client()
    base_url = str(os.environ.get("PUBLIC_BASE_URL", "")).rstrip("/")
    canonical = f"{base_url}/holdings/site/{slug}/" if base_url else f"/holdings/site/{slug}/"
    source_cards = "".join(
        f'<article class="card"><h2>{html.escape(s["heading"])}</h2><p>{html.escape(s["text"])}</p>'
        + (f'<a rel="nofollow noopener" target="_blank" href="{html.escape(s["url"], quote=True)}">Fuente consultada ↗</a>' if s["url"] else "")
        + "</article>" for s in sections
    )
    adsense = (f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={html.escape(client)}" crossorigin="anonymous"></script>' if client else "")
    doc = f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(display)} · Guía</title><meta name="description" content="Guía útil y actualizada sobre {html.escape(topic[:150])}"><link rel="canonical" href="{html.escape(canonical, quote=True)}">{adsense}<style>*{{box-sizing:border-box}}body{{margin:0;background:#090909;color:#f5f1e8;font-family:Inter,system-ui,sans-serif}}.wrap{{max-width:1040px;margin:auto;padding:28px}}nav{{display:flex;justify-content:space-between;gap:20px;border-bottom:1px solid #33271d;padding:12px 0;color:#d9b97b}}.hero{{padding:72px 0 40px}}h1{{font-size:clamp(40px,7vw,78px);line-height:.98;letter-spacing:-.05em;margin:12px 0}}p{{color:#c3b9ad;line-height:1.7}}.pill{{display:inline-block;border:1px solid #614a32;border-radius:999px;padding:7px 10px;color:#e0bf84}}.grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}}.card{{border:1px solid #342a22;background:#12100e;border-radius:16px;padding:22px}}.card a{{color:#e7c783}}footer{{margin-top:48px;border-top:1px solid #33271d;padding:28px 0;color:#8f857c;font-size:13px}}@media(max-width:720px){{.grid{{grid-template-columns:1fr}}.hero{{padding-top:48px}}}}</style></head><body><div class="wrap"><nav><b>{html.escape(display)}</b><span>ZAR Sites</span></nav><main><section class="hero"><span class="pill">Contenido útil · crecimiento orgánico</span><h1>{html.escape(topic)}</h1><p>Resumen práctico construido a partir de fuentes públicas. Este sitio prioriza contenido útil y no utiliza tráfico o clics artificiales.</p></section><section class="grid">{source_cards}</section></main><footer><a href="privacy.html" style="color:#bfa67b">Privacidad</a> · ZAR Sites · Actualizado {datetime.now().date().isoformat()}</footer></div></body></html>'''
    privacy = '''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Privacidad</title><body style="font-family:system-ui;max-width:760px;margin:50px auto;padding:20px"><h1>Privacidad</h1><p>Este sitio puede utilizar cookies y servicios publicitarios/analíticos de terceros cuando estén configurados. El operador debe completar y adaptar esta política a los servicios realmente activos y a la normativa aplicable antes de monetizar.</p><p><a href="./">Volver</a></p></body></html>'''
    (root / "index.html").write_text(doc, encoding="utf-8")
    (root / "privacy.html").write_text(privacy, encoding="utf-8")
    (root / "robots.txt").write_text("User-agent: *\nAllow: /\nSitemap: sitemap.xml\n", encoding="utf-8")
    (root / "sitemap.xml").write_text(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>{html.escape(canonical)}</loc></url></urlset>', encoding="utf-8")
    if pub:
        (root / "ads.txt").write_text(f"google.com, {pub}, DIRECT, f08c47fec0942fa0\n", encoding="utf-8")
    row = {
        "id": uuid.uuid4().hex[:16], "slug": slug, "name": display, "topic": topic,
        "created_at": _now(), "updated_at": _now(), "relative_url": f"/holdings/site/{slug}/",
        "canonical": canonical, "adsense_embedded": bool(client), "adsense_status": "NEEDS_APPROVAL" if client else "NOT_CONFIGURED",
        "deployment": None, "domain": None, "domain_cost": 0.0, "organic_only": True,
        "sources": [x.get("url") for x in rows[:8] if x.get("url")],
    }
    reg = _read_registry(scope_id); reg.append(row); _write_registry(scope_id, reg)
    holdings.update_company(scope_id, "sites", action=f"Sitio creado: {display}", event="SITE_CREATED", event_detail=canonical)
    if queue_promotion:
        try:
            from . import media_company
            media_company.queue_story(scope_id, f"Vídeo corto para atraer audiencia orgánica al artículo: {topic}", goal="tráfico orgánico útil", platform="tiktok")
        except Exception:
            pass
    return row


def queue_site(scope_id, topic, name=""):
    return holdings.queue_task(scope_id, "sites", "build_site", {"topic": str(topic or "")[:300], "name": str(name or "")[:120]}, requires_approval=False)



def _site_config(scope_id):
    state = holdings.read(scope_id)
    return dict(((state.get("companies") or {}).get("sites") or {}).get("config") or {})


def _domain_spend_today(scope_id):
    today = datetime.now(timezone.utc).date().isoformat()
    total = 0.0
    for row in holdings.read(scope_id).get("ledger") or []:
        if row.get("company") != "sites" or row.get("source") != "vercel_domain":
            continue
        if not str(row.get("timestamp") or "").startswith(today):
            continue
        total += abs(float(row.get("amount") or 0))
    return round(total, 6)


def _domain_candidates(site):
    base = re.sub(r"[^a-z0-9]+", "", str(site.get("name") or site.get("topic") or "zar").lower())[:22]
    if len(base) < 4:
        base = "zar" + uuid.uuid4().hex[:6]
    short = base[:16]
    return [f"{base}.com", f"{base}.es", f"{short}guia.com"]


def _extract_domain_quote(payload, requested):
    """Best-effort normalizer for Vercel Registrar search response shapes."""
    rows = payload
    if isinstance(payload, dict):
        for key in ("results", "domains", "data"):
            if isinstance(payload.get(key), list):
                rows = payload[key]
                break
        else:
            if requested in payload and isinstance(payload[requested], dict):
                rows = [{"domain": requested, **payload[requested]}]
            elif payload.get("domain") or payload.get("name"):
                rows = [payload]
            else:
                rows = []
    if not isinstance(rows, list):
        rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("domain") or row.get("name") or row.get("id") or "").lower()
        if name and name != requested.lower():
            continue
        available = row.get("available")
        if available is None:
            available = row.get("availability") in {True, "available", "AVAILABLE"}
        price = row.get("price")
        if isinstance(price, dict):
            price = price.get("purchase") or price.get("buy") or price.get("amount") or price.get("value")
        if price is None:
            price = row.get("purchasePrice") or row.get("purchase_price") or row.get("amount")
        try:
            price = float(price)
        except (TypeError, ValueError):
            price = 0.0
        return {"domain": requested, "available": bool(available), "price": price, "raw": row}
    return {"domain": requested, "available": False, "price": 0.0, "raw": None}



def _usd_to_eur_rate():
    env = os.environ.get("ZAR_USD_EUR_RATE", "").strip()
    if env:
        try:
            value = float(env)
            if 0.4 <= value <= 1.6:
                return value
        except ValueError:
            pass
    # ECB reference rate is quoted as USD per EUR; invert to get EUR per USD.
    try:
        r = requests.get("https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml", timeout=12)
        if r.ok:
            m = re.search(r"currency=['\"]USD['\"]\s+rate=['\"]([0-9.]+)['\"]", r.text)
            if m:
                usd_per_eur = float(m.group(1))
                if usd_per_eur > 0:
                    return 1.0 / usd_per_eur
    except Exception:
        pass
    raise RuntimeError("No se pudo obtener USD/EUR para aplicar el presupuesto de dominios.")


def _maybe_auto_domain(scope_id, site):
    cfg = _site_config(scope_id)
    if not (cfg.get("allow_domain_reinvestment") and cfg.get("auto_domain_purchase")):
        return {"ok": False, "skipped": "auto domain purchase disabled"}
    if not status().get("vercel_configured") or not status().get("domain_registrant_configured"):
        return {"ok": False, "skipped": "Vercel/registrant not configured"}
    max_one = max(0.0, min(float(cfg.get("max_domain_eur") or 20.0), 500.0))
    daily_cap = max(0.0, min(float(cfg.get("domain_daily_budget_eur") or 40.0), 2000.0))
    spent = _domain_spend_today(scope_id)
    profit = _sites_profit(scope_id)
    if spent >= daily_cap or profit <= 0:
        return {"ok": False, "skipped": "daily budget/profit gate"}
    for domain in _domain_candidates(site):
        try:
            search = search_domains([domain])
            quote_row = _extract_domain_quote(search.get("results"), domain)
        except Exception:
            continue
        price_usd = float(quote_row.get("price") or 0)
        if not quote_row.get("available") or price_usd <= 0:
            continue
        try:
            price_eur = price_usd * _usd_to_eur_rate()
        except Exception:
            continue
        if price_eur > max_one or spent + price_eur > daily_cap or price_eur > profit:
            continue
        # auto_domain_purchase is an explicit standing authorization stored by the user.
        return buy_domain(scope_id, site.get("slug") or "", domain, price_usd, confirmed=True)
    return {"ok": False, "skipped": "no eligible domain quote"}


def configure_network(scope_id, *, enabled, seed_topic=None, max_sites=None,
                      auto_deploy_vercel=None, allow_domain_reinvestment=None,
                      auto_domain_purchase=None, max_domain_eur=None,
                      domain_daily_budget_eur=None):
    patch = {"auto_expand": bool(enabled)}
    if seed_topic is not None:
        patch["seed_topic"] = re.sub(r"\s+", " ", str(seed_topic)).strip()[:240]
    if max_sites is not None:
        patch["max_sites"] = max(1, min(int(max_sites), 80))
    if auto_deploy_vercel is not None:
        patch["auto_deploy_vercel"] = bool(auto_deploy_vercel)
    if allow_domain_reinvestment is not None:
        patch["allow_domain_reinvestment"] = bool(allow_domain_reinvestment)
    if auto_domain_purchase is not None:
        patch["auto_domain_purchase"] = bool(auto_domain_purchase)
    if max_domain_eur is not None:
        patch["max_domain_eur"] = max(0.0, min(float(max_domain_eur), 500.0))
    if domain_daily_budget_eur is not None:
        patch["domain_daily_budget_eur"] = max(0.0, min(float(domain_daily_budget_eur), 2000.0))
    d = holdings.update_company(scope_id, "sites", config=patch,
                                action="Red ZAR Sites activada." if enabled else "Expansión automática de Sites desactivada.",
                                event="NETWORK_POLICY", event_detail=str(patch))
    if enabled:
        # Start the company and queue the first useful site immediately if the network is empty.
        d = holdings.set_company_state(scope_id, "sites", "start")
        if not _read_registry(scope_id) and not holdings.next_task(scope_id, "sites"):
            queue_site(scope_id, patch.get("seed_topic") or _site_config(scope_id).get("seed_topic") or "guías útiles España")
    return d


def _autonomous_growth(scope_id):
    cfg = _site_config(scope_id)
    if not cfg.get("auto_expand"):
        return None
    registry = _read_registry(scope_id)
    max_sites = max(1, min(int(cfg.get("max_sites") or 12), 80))
    if len(registry) >= max_sites:
        return f"Sites: red en límite configurado ({len(registry)}/{max_sites})."
    company = (holdings.read(scope_id).get("companies") or {}).get("sites") or {}
    cycles = int(company.get("cycles") or 0)
    interval = max(6, min(int(cfg.get("growth_cycle_interval") or 360), 8640))
    # The first site is queued on activation; then create at most one new site per interval.
    if registry and cycles % interval != 0:
        return None
    seed = str(cfg.get("seed_topic") or "guías útiles España")
    ideas = scout_ideas(seed, limit=6).get("ideas") or []
    existing_topics = {str(x.get("topic") or "").lower() for x in registry}
    idea = next((x for x in ideas if str(x.get("topic") or "").lower() not in existing_topics), None)
    if not idea:
        topic = f"{seed} · guía {len(registry)+1}"
    else:
        topic = idea.get("topic") or seed
    site = build_site(scope_id, topic, queue_promotion=True)
    parts = [f"Sites: expansión automática creó {site['name']}"]
    if cfg.get("auto_deploy_vercel") and status().get("vercel_configured"):
        try:
            dep = deploy_vercel(scope_id, site["slug"])
            site = dep.get("site") or site
            parts.append("Vercel desplegado")
        except Exception as exc:
            parts.append(f"deploy pendiente: {str(exc)[:120]}")
    if cfg.get("auto_domain_purchase"):
        try:
            dom = _maybe_auto_domain(scope_id, site)
            if dom.get("ok"):
                parts.append(f"dominio {dom.get('domain')} comprado con beneficio realizado")
            elif dom.get("skipped"):
                parts.append("dominio: " + str(dom.get("skipped"))[:100])
        except Exception as exc:
            parts.append(f"dominio pendiente: {str(exc)[:120]}")
    return " · ".join(parts)


def process_one(scope_id):
    task = holdings.next_task(scope_id, "sites")
    if not task:
        growth = _autonomous_growth(scope_id)
        return growth or "Sites: heartbeat · esperando el siguiente ciclo de crecimiento/métricas."
    if task.get("kind") != "build_site":
        holdings.update_task(scope_id, "sites", task["id"], status="SKIPPED", result={"reason": "tipo no soportado"})
        return "Sites: tarea no soportada omitida."
    p = task.get("payload") or {}
    site = build_site(scope_id, p.get("topic"), p.get("name") or "", queue_promotion=True)
    result = site
    parts = [f"Sites: publicado {site['name']} en {site['relative_url']}"]
    cfg = _site_config(scope_id)
    if cfg.get("auto_deploy_vercel") and status().get("vercel_configured"):
        try:
            dep = deploy_vercel(scope_id, site["slug"]); result = dep.get("site") or site
            parts.append("Vercel desplegado")
        except Exception as exc:
            parts.append(f"deploy pendiente: {str(exc)[:120]}")
    if cfg.get("auto_domain_purchase"):
        try:
            dom = _maybe_auto_domain(scope_id, result)
            if dom.get("ok"): parts.append(f"dominio {dom.get('domain')} comprado con beneficio realizado")
        except Exception as exc:
            parts.append(f"dominio pendiente: {str(exc)[:120]}")
    holdings.update_task(scope_id, "sites", task["id"], status="DONE", result=result)
    return " · ".join(parts)


def _vercel_headers():
    token = os.environ.get("VERCEL_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Falta VERCEL_TOKEN.")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _team_query():
    team = os.environ.get("VERCEL_TEAM_ID", "").strip()
    return {"teamId": team} if team else {}


def deploy_vercel(scope_id, slug):
    row = next((x for x in _read_registry(scope_id) if x.get("slug") == slug), None)
    if not row:
        raise KeyError("Sitio no encontrado.")
    root = _public_root() / slug
    if not root.exists():
        raise FileNotFoundError("Archivos del sitio no encontrados.")
    files = []
    for p in root.iterdir():
        if p.is_file():
            files.append({"file": p.name, "data": base64.b64encode(p.read_bytes()).decode("ascii"), "encoding": "base64"})
    project = re.sub(r"[^a-z0-9-]", "-", f"zar-site-{slug}".lower())[:90]
    payload = {"name": project, "project": project, "files": files, "target": "production", "projectSettings": {"framework": None}}
    r = requests.post("https://api.vercel.com/v13/deployments", headers=_vercel_headers(), params=_team_query(), json=payload, timeout=75)
    if not r.ok:
        raise RuntimeError(f"Vercel HTTP {r.status_code}: {r.text[:900]}")
    data = r.json(); url = data.get("url") or ""
    reg = _read_registry(scope_id)
    for x in reg:
        if x.get("slug") == slug:
            x["deployment"] = {"id": data.get("id"), "url": ("https://" + url) if url and not url.startswith("http") else url, "project": project, "ready_state": data.get("readyState")}
            x["updated_at"] = _now(); row = x; break
    _write_registry(scope_id, reg)
    holdings.update_company(scope_id, "sites", action=f"Deploy Vercel creado: {url}", event="DEPLOY", event_detail=str(data.get("id") or url))
    return {"ok": True, "site": row, "deployment": row.get("deployment")}


def search_domains(names):
    cleaned = []
    for name in (names or []):
        n = re.sub(r"[^a-z0-9.-]", "", str(name or "").lower()).strip(".-")
        if "." in n and n not in cleaned:
            cleaned.append(n[:253])
    if not cleaned:
        raise ValueError("Indica al menos un dominio completo, por ejemplo ejemplo.com.")
    r = requests.post("https://api.vercel.com/v1/registrar/domains/search", json={"domains": cleaned[:20]}, timeout=30)
    if not r.ok:
        raise RuntimeError(f"Vercel domain search HTTP {r.status_code}: {r.text[:700]}")
    return {"ok": True, "results": r.json(), "purchase_authority": False}


def _sites_profit(scope_id):
    d = holdings.recalculate(scope_id)
    return float((((d.get("companies") or {}).get("sites") or {}).get("metrics") or {}).get("profit_realized") or 0)


def buy_domain(scope_id, slug, domain, expected_price, *, confirmed=False):
    domain = re.sub(r"[^a-z0-9.-]", "", str(domain or "").lower()).strip(".-")
    expected_price = float(expected_price or 0)
    if not domain or "." not in domain or expected_price <= 0:
        raise ValueError("Dominio/precio no válidos.")
    st = holdings.read(scope_id); cfg = st["companies"]["sites"].get("config") or {}
    max_domain = float(cfg.get("max_domain_eur") or 20.0)
    available = _sites_profit(scope_id)
    if available <= 0:
        decision = gate("Comprar dominio con beneficios realizados de ZAR Sites", {"domain": domain, "expected_price_usd": expected_price, "profit_realized_eur": available, "limit_eur": max_domain}, "high")
        return {"ok": False, "requires_review": True, "message": f"ZAR Sites solo puede reinvertir beneficio realizado. Disponible: {available:.2f} €.", "decision": decision}
    rate = _usd_to_eur_rate()
    expected_price_eur = round(expected_price * rate, 6)
    decision = gate("Comprar dominio con beneficios realizados de ZAR Sites", {"domain": domain, "expected_price_usd": expected_price, "expected_price_eur": expected_price_eur, "profit_realized_eur": available, "limit_eur": max_domain}, "high")
    if expected_price_eur > max_domain:
        return {"ok": False, "requires_review": True, "message": f"Precio aprox. {expected_price_eur:.2f} € (${expected_price:.2f}) supera el límite {max_domain:.2f} €.", "decision": decision}
    if available + 1e-9 < expected_price_eur:
        return {"ok": False, "requires_review": True, "message": f"ZAR Sites solo puede reinvertir beneficio realizado. Disponible: {available:.2f} €; dominio aprox.: {expected_price_eur:.2f} €.", "decision": decision}
    if not cfg.get("allow_domain_reinvestment"):
        return {"ok": False, "requires_review": True, "message": "Activa primero la reinversión de dominios en ZAR Sites.", "decision": decision}
    if not confirmed:
        return {"ok": False, "requires_review": True, "message": "La compra real del dominio requiere confirmación explícita.", "decision": decision}
    registrant_raw = os.environ.get("ZAR_DOMAIN_REGISTRANT_JSON", "").strip()
    if not registrant_raw:
        raise RuntimeError("Falta ZAR_DOMAIN_REGISTRANT_JSON con los datos del titular.")
    try:
        registrant = json.loads(registrant_raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("ZAR_DOMAIN_REGISTRANT_JSON no es JSON válido.") from exc
    body = {"autoRenew": True, "years": 1, "expectedPrice": expected_price, "contactInformation": registrant, "languageCode": "es"}
    r = requests.post(f"https://api.vercel.com/v1/registrar/domains/{quote(domain, safe='')}/buy", headers=_vercel_headers(), params=_team_query(), json=body, timeout=60)
    if not r.ok:
        raise RuntimeError(f"Compra dominio HTTP {r.status_code}: {r.text[:900]}")
    payload = r.json()
    holdings.add_ledger(scope_id, "sites", "cost", expected_price_eur, currency="EUR", status="collected", source="vercel_domain", reference=f"domain:{domain}", note=f"Registro Vercel {domain}: ${expected_price:.2f} USD · convertido con referencia ECB {rate:.6f} EUR/USD; impuestos del registrador pueden liquidarse aparte.", verified=True)
    reg = _read_registry(scope_id)
    target = None
    for x in reg:
        if x.get("slug") == slug:
            x["domain"] = domain; x["domain_cost_usd"] = expected_price; x["domain_cost_eur"] = expected_price_eur; x["domain_order"] = payload; x["updated_at"] = _now(); target = x; break
    _write_registry(scope_id, reg)
    # If the site was deployed through ZAR, bind the purchased domain to that Vercel project.
    if target and target.get("deployment", {}).get("project"):
        project = target["deployment"]["project"]
        rr = requests.post(f"https://api.vercel.com/v10/projects/{quote(project, safe='')}/domains", headers=_vercel_headers(), params=_team_query(), json={"name": domain}, timeout=40)
        target["domain_binding"] = rr.json() if rr.headers.get("content-type", "").startswith("application/json") else {"status": rr.status_code, "text": rr.text[:800]}
        reg = _read_registry(scope_id)
        for i, x in enumerate(reg):
            if x.get("slug") == slug: reg[i] = target; break
        _write_registry(scope_id, reg)
    holdings.update_company(scope_id, "sites", action=f"Dominio comprado con beneficio realizado: {domain}", event="DOMAIN_PURCHASE", event_detail=f"{domain} · ${expected_price:.2f} USD ≈ {expected_price_eur:.2f} EUR")
    return {"ok": True, "domain": domain, "cost": expected_price_eur, "cost_eur": expected_price_eur, "cost_usd": expected_price, "order": payload, "site": target, "decision": decision}


def configure_policy(scope_id, *, allow_domain_reinvestment=None, max_domain_eur=None, auto_domain_purchase=None, domain_daily_budget_eur=None):
    patch = {}
    if allow_domain_reinvestment is not None:
        patch["allow_domain_reinvestment"] = bool(allow_domain_reinvestment)
    if auto_domain_purchase is not None:
        patch["auto_domain_purchase"] = bool(auto_domain_purchase)
    if max_domain_eur is not None:
        value = max(0.0, min(float(max_domain_eur), 500.0))
        patch["max_domain_eur"] = value
    if domain_daily_budget_eur is not None:
        patch["domain_daily_budget_eur"] = max(0.0, min(float(domain_daily_budget_eur), 2000.0))
    return holdings.update_company(scope_id, "sites", config=patch, action="Política de reinversión Sites actualizada.", event="POLICY", event_detail=str(patch))


def _adsense_headers():
    token = os.environ.get("GOOGLE_ADSENSE_ACCESS_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Falta GOOGLE_ADSENSE_ACCESS_TOKEN (scope adsense.readonly o adsense).")
    return {"Authorization": f"Bearer {token}"}


def _adsense_account():
    account = os.environ.get("GOOGLE_ADSENSE_ACCOUNT", "").strip()
    if account and not account.startswith("accounts/"):
        account = "accounts/" + account
    return account


def _parse_money(text):
    raw = str(text or "").replace("\xa0", " ").strip()
    currency = "EUR" if "€" in raw or "EUR" in raw.upper() else ("USD" if "$" in raw or "USD" in raw.upper() else "EUR")
    cleaned = re.sub(r"[^0-9,.-]", "", raw)
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try: amount = float(cleaned)
    except ValueError: amount = 0.0
    return amount, currency


def sync_adsense(scope_id):
    account = _adsense_account()
    headers = _adsense_headers()
    if not account:
        r0 = requests.get("https://adsense.googleapis.com/v2/accounts", headers=headers, timeout=30)
        if not r0.ok:
            raise RuntimeError(f"AdSense accounts HTTP {r0.status_code}: {r0.text[:600]}")
        accs = r0.json().get("accounts") or []
        if not accs:
            raise RuntimeError("No hay cuentas AdSense accesibles.")
        account = accs[0].get("name") or ""
    params = [("dateRange", "LAST_30_DAYS"), ("metrics", "ESTIMATED_EARNINGS"), ("metrics", "PAGE_VIEWS"), ("metrics", "PAGE_VIEWS_RPM"), ("currencyCode", "EUR")]
    rep = requests.get(f"https://adsense.googleapis.com/v2/{account}/reports:generate", headers=headers, params=params, timeout=40)
    if not rep.ok:
        raise RuntimeError(f"AdSense report HTTP {rep.status_code}: {rep.text[:800]}")
    report = rep.json(); headers_meta = report.get("headers") or []; cells = ((report.get("totals") or {}).get("cells") or [])
    totals = {}
    for idx, h in enumerate(headers_meta):
        value = (cells[idx].get("value") if idx < len(cells) and isinstance(cells[idx], dict) else None)
        totals[h.get("name") or str(idx)] = value
    estimated = float(totals.get("ESTIMATED_EARNINGS") or 0); page_views = int(float(totals.get("PAGE_VIEWS") or 0)); rpm = float(totals.get("PAGE_VIEWS_RPM") or 0)
    payments = requests.get(f"https://adsense.googleapis.com/v2/{account}/payments", headers=headers, timeout=35)
    if not payments.ok:
        raise RuntimeError(f"AdSense payments HTTP {payments.status_code}: {payments.text[:800]}")
    added = 0
    for p in payments.json().get("payments") or []:
        name = str(p.get("name") or "")
        if name.endswith("/unpaid") or "youtube-" in name:
            continue
        amount, currency = _parse_money(p.get("amount"))
        if amount <= 0:
            continue
        before = len(holdings.read(scope_id).get("ledger") or [])
        holdings.add_ledger(scope_id, "sites", "revenue", amount, currency=currency, status="collected", source="adsense_payment", reference=name, note="Pago AdSense verificado vía API", verified=True)
        after = len(holdings.read(scope_id).get("ledger") or [])
        added += int(after > before)
    holdings.update_company(scope_id, "sites", metrics={"adsense_estimated_30d": round(estimated, 4), "page_views_30d": page_views, "page_rpm_30d": round(rpm, 4)}, action=f"AdSense sincronizado · {page_views} vistas/30d · estimado {estimated:.2f} EUR · {added} pago(s) nuevo(s)", event="ADSENSE_SYNC", event_detail=account)
    return {"ok": True, "account": account, "estimated_30d": estimated, "page_views_30d": page_views, "page_rpm_30d": rpm, "payments_added": added, "note": "Solo pagos AdSense acreditados se registran como ingreso cobrado; el estimado se muestra aparte."}
