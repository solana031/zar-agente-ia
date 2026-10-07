"""Background runtime for ZAR Holdings companies."""
from __future__ import annotations
import time
from . import holdings, commerce_company, media_company, sites_company, business_orchestration


def cycle_scope(scope_id):
    d=holdings.read(scope_id)
    if d.get("global_stop"):
        return {"ok":True,"stopped":True}
    business_orchestration.tick(scope_id)
    # SHADOW cannot invoke company handlers (they may write externally).
    if d.get("orchestration", {}).get("mode") == "SHADOW":
        return {"ok":True,"shadow":True,"external_actions":False}
    results={}
    for key in ("commerce","media","web_agency","sites"):
        c=d.get("companies",{}).get(key) or {}
        if c.get("state") != "RUNNING":
            continue
        try:
            if key=="commerce":
                # External Shopify sync is deliberately sparse. No purchase is ever issued here.
                if commerce_company.status().get("shopify_configured") and int(c.get("cycles") or 0) % 30 == 0:
                    r=commerce_company.sync_paid_orders(scope_id); action=f"Commerce: Shopify sincronizado ({r.get('ledger_added',0)} nuevos)."
                else: action="Commerce: heartbeat · esperando catálogo/pedidos autorizados."
            elif key=="media":
                from .business_dispatch import BusinessOrchestrator
                action=BusinessOrchestrator.execute("media",scope_id,{})
            elif key=="sites":
                action=sites_company.process_one(scope_id)
                # Read-only revenue sync is sparse and never manufactures revenue.
                if sites_company.status().get("adsense_reporting_configured") and int(c.get("cycles") or 0) % 30 == 0:
                    try:
                        r=sites_company.sync_adsense(scope_id)
                        action += f" · AdSense {r.get('page_views_30d',0)} vistas/30d"
                    except Exception as exc:
                        action += f" · AdSense pendiente: {str(exc)[:180]}"
            else: action="Web Agency: heartbeat · esperando discovery/demo/outreach autorizados."
            holdings.complete_cycle(scope_id,key,action); results[key]={"ok":True,"action":action}
        except Exception as exc:
            holdings.complete_cycle(scope_id,key,f"{key}: error controlado",error=str(exc)); results[key]={"ok":False,"error":str(exc)}
    return {"ok":True,"results":results}


def run_forever(stop_event=None, interval=10):
    while stop_event is None or not stop_event.is_set():
        try:
            for scope_id in holdings.active_scope_ids():
                cycle_scope(scope_id)
        except Exception:
            pass
        time.sleep(max(5,int(interval)))
