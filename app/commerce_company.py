"""ZAR Commerce: Shopify + supplier bridge, designed for bounded automation."""
from __future__ import annotations

import os
import requests
import re

from . import holdings
from .web_search import public_search_results
from .jev_decision import gate

API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2026-10")


def _shop():
    raw = os.environ.get("SHOPIFY_SHOP_DOMAIN", "").strip().replace("https://", "").replace("http://", "").strip("/")
    return raw


def _token():
    return os.environ.get("SHOPIFY_ADMIN_ACCESS_TOKEN", "").strip()


def status():
    supplier = bool(os.environ.get("ZAR_SUPPLIER_ORDER_WEBHOOK", "").strip())
    return {
        "shopify_configured": bool(_shop() and _token()),
        "shop_domain": _shop(),
        "api_version": API_VERSION,
        "supplier_configured": supplier,
        "supplier_catalog_configured": bool(os.environ.get("ZAR_SUPPLIER_CATALOG_URL", "").strip()),
        "can_create_draft_products": bool(_shop() and _token()),
        "can_auto_fulfill": supplier,
    }


def _graphql(query, variables=None, timeout=35):
    from .commerce_adapters import ShopifyAdapter
    return ShopifyAdapter().graphql(query,variables)


def sync_paid_orders(scope_id):
    from .commerce_workspace import operate
    return {'ok':True, **operate(scope_id,'shopify_sync',{})}


def create_draft_product(scope_id, product):
    title = str((product or {}).get("title") or "").strip()
    if not title:
        raise ValueError("Falta title.")
    if (product or {}).get("confirmed") is not True or holdings.read(scope_id).get("global_stop"):
        return {"ok":False,"requires_review":True,"message":"Confirma escritura externa y revisa STOP GLOBAL."}
    decision = gate("Crear producto en Shopify", {"product": product, "company":"commerce"}, "medium")
    if decision["requires_review"] and not bool((product or {}).get("confirmed")):
        return {"ok": False, "requires_review": True, "decision": decision, "message": "Jev/política exige confirmación antes de escribir en Shopify."}
    mutation = """mutation ZARProduct($product:ProductCreateInput!){productCreate(product:$product){product{id title status} userErrors{field message}}}"""
    inp = {"title": title, "status":"DRAFT"}
    for k in ("descriptionHtml","vendor","productType"):
        if product.get(k): inp[k] = product[k]
    data = _graphql(mutation, {"product": inp})
    result = data.get("productCreate") or {}
    if result.get("userErrors"):
        raise RuntimeError("Shopify: " + str(result["userErrors"])[:800])
    p = result.get("product") or {}
    holdings.update_company(scope_id, "commerce", action=f"Producto borrador creado: {p.get('title') or title}", event="SHOPIFY_DRAFT", event_detail=str(p))
    return {"ok": True, "product": p, "decision": decision}


def margin(source_cost, sale_price, fees=None, shipping=None):
    from .commerce_pricing import number,fmt
    cost=number(source_cost);sale=number(sale_price);fee=number(fees);ship=number(shipping)
    profit=None if any(x is None for x in (cost,sale,fee,ship)) else sale-cost-fee-ship
    return {'source_cost':fmt(cost),'sale_price':fmt(sale),'fees':fmt(fee),'shipping':fmt(ship),
        'profit':fmt(profit),'margin_pct':fmt(profit/sale*100) if profit is not None and sale else None,
        'classification':'ESTIMADA','note':'Cálculo parcial; pricing completo en Commerce. Desconocidos no equivalen a cero.'}


def supplier_order(order, confirmed=False):
    return {'ok':False,'requires_review':True,'message':'Usa Commerce: quote verificable, reserva Wallet, aprobación vinculada y ejecución idempotente. confirmed genérico no autoriza una compra.'}


_PRICE_RE = re.compile(r"(?:€|EUR\s*)\s*(\d{1,5}(?:[.,]\d{1,2})?)|(?:(\d{1,5}(?:[.,]\d{1,2})?)\s*(?:€|EUR))", re.I)

def scout(scope_id, query, sale_price=0):
    """Research supplier candidates. Structured catalogs are preferred; web hits stay unverified."""
    query=str(query or "").strip()
    if not query: raise ValueError("Falta el producto a buscar.")
    sale=float(sale_price or 0)
    candidates=[]; catalog=os.environ.get("ZAR_SUPPLIER_CATALOG_URL","").strip()
    if catalog:
        try:
            r=requests.get(catalog,params={"q":query},headers={"Authorization":"Bearer "+os.environ.get("ZAR_SUPPLIER_API_TOKEN","").strip()} if os.environ.get("ZAR_SUPPLIER_API_TOKEN","").strip() else {},timeout=30)
            if r.ok:
                data=r.json(); rows=data if isinstance(data,list) else (data.get("products") or data.get("items") or data.get("results") or [])
                for x in rows[:20]:
                    if not isinstance(x,dict): continue
                    cost=x.get("cost",x.get("price",x.get("unit_price")))
                    try: cost=float(str(cost).replace(",","."))
                    except Exception: cost=None
                    row={"title":x.get("title") or x.get("name") or x.get("sku") or "Producto","cost":cost,"currency":x.get("currency"),"url":x.get("url") or x.get("product_url"),"sku":x.get("sku"),"verified":False,"catalog_observed":True,"cost_classification":"REAL" if cost is not None else "NO DISPONIBLE","dropshipping":x.get("dropshipping"),"source":"supplier_catalog"}
                    if cost is not None and sale: row["margin"]=margin(cost,sale,x.get("fees"),x.get("shipping"))
                    candidates.append(row)
        except Exception as exc:
            holdings.update_company(scope_id,"commerce",error="Catálogo proveedor no disponible; revisar configuración/contrato.")
    if not candidates:
        result=public_search_results(query+" proveedor mayorista precio",limit=10)
        for x in result.get("results") or []:
            blob=(str(x.get("title") or "")+" "+str(x.get("snippet") or ""))
            vals=[]
            for m in _PRICE_RE.finditer(blob):
                try:
                    v=float((m.group(1) or m.group(2)).replace(",","."))
                    if 0.05 <= v <= 100000: vals.append(v)
                except Exception: pass
            candidates.append({"title":x.get("title") or "Resultado proveedor","cost":min(vals) if vals else None,"currency":"EUR","url":x.get("url"),"verified":False,"cost_classification":"ESTIMADA" if vals else "NO DISPONIBLE","dropshipping":None,"source":result.get("provider") or "web","margin":margin(min(vals),sale) if vals and sale else None})
    decision=gate("Seleccionar producto/proveedor para análisis comercial",{"query":query,"sale_price":sale,"candidates":candidates[:10]},"medium")
    holdings.update_company(scope_id,"commerce",action=f"Scouting: {len(candidates)} candidato(s) para «{query}»; sin compras automáticas.",event="SCOUT",event_detail=query)
    return {"ok":True,"query":query,"sale_price":sale,"candidates":candidates[:20],"decision":decision,"purchase_authority":False}
