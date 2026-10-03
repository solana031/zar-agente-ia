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
    if not _shop() or not _token():
        raise RuntimeError("Faltan SHOPIFY_SHOP_DOMAIN y SHOPIFY_ADMIN_ACCESS_TOKEN.")
    url = f"https://{_shop()}/admin/api/{API_VERSION}/graphql.json"
    r = requests.post(url, headers={"X-Shopify-Access-Token": _token(), "Content-Type":"application/json"}, json={"query":query,"variables":variables or {}}, timeout=timeout)
    if not r.ok:
        raise RuntimeError(f"Shopify HTTP {r.status_code}: {r.text[:700]}")
    data = r.json()
    if data.get("errors"):
        raise RuntimeError("Shopify GraphQL: " + str(data["errors"])[:900])
    return data.get("data") or {}


def sync_paid_orders(scope_id):
    query = """query ZAROrders($first:Int!){orders(first:$first,sortKey:CREATED_AT,reverse:true){nodes{id name createdAt displayFinancialStatus displayFulfillmentStatus totalPriceSet{shopMoney{amount currencyCode}}}}}"""
    data = _graphql(query, {"first": 50})
    rows = (data.get("orders") or {}).get("nodes") or []
    added = 0
    for o in rows:
        status_name = str(o.get("displayFinancialStatus") or "").upper()
        if status_name not in {"PAID", "PARTIALLY_REFUNDED"}:
            continue
        money = ((o.get("totalPriceSet") or {}).get("shopMoney") or {})
        amount = float(money.get("amount") or 0)
        ref = str(o.get("id") or o.get("name") or "")
        before = len(holdings.read(scope_id).get("ledger") or [])
        holdings.add_ledger(scope_id, "commerce", "revenue", amount, currency=money.get("currencyCode") or "EUR", status="collected", source="shopify", reference=ref, note=o.get("name") or "", verified=True)
        after = len(holdings.read(scope_id).get("ledger") or [])
        added += int(after > before)
    holdings.update_company(scope_id, "commerce", action=f"Shopify sincronizado · {len(rows)} pedidos revisados · {added} ingreso(s) nuevo(s)", event="SYNC", event_detail="Ingresos Shopify sincronizados")
    return {"ok": True, "orders_checked": len(rows), "ledger_added": added}


def create_draft_product(scope_id, product):
    title = str((product or {}).get("title") or "").strip()
    if not title:
        raise ValueError("Falta title.")
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


def margin(source_cost, sale_price, fees=0, shipping=0):
    source_cost=float(source_cost or 0); sale_price=float(sale_price or 0); fees=float(fees or 0); shipping=float(shipping or 0)
    profit=sale_price-source_cost-fees-shipping
    return {"source_cost":source_cost,"sale_price":sale_price,"fees":fees,"shipping":shipping,"profit":round(profit,2),"margin_pct":round((profit/sale_price*100),2) if sale_price else 0.0}


def supplier_order(order, confirmed=False):
    url = os.environ.get("ZAR_SUPPLIER_ORDER_WEBHOOK", "").strip()
    if not url:
        return {"ok":False,"configured":False,"requires_review":True,"message":"Configura ZAR_SUPPLIER_ORDER_WEBHOOK para enviar pedidos directamente al proveedor."}
    decision = gate("Comprar al proveedor y enviar directamente al cliente", {"order":order}, "high")
    if not confirmed:
        return {"ok":False,"requires_review":True,"decision":decision,"message":"La compra al proveedor requiere confirmación explícita."}
    token=os.environ.get("ZAR_SUPPLIER_API_TOKEN","").strip()
    headers={"Content-Type":"application/json"}
    if token: headers["Authorization"]="Bearer "+token
    r=requests.post(url,headers=headers,json=order,timeout=45)
    if not r.ok: raise RuntimeError(f"Proveedor HTTP {r.status_code}: {r.text[:700]}")
    try: payload=r.json()
    except ValueError: payload={"text":r.text[:1000]}
    return {"ok":True,"provider_result":payload,"decision":decision}


_PRICE_RE = re.compile(r"(?:€|EUR\s*)?\s*(\d{1,5}(?:[.,]\d{1,2})?)\s*(?:€|EUR)?", re.I)

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
                    row={"title":x.get("title") or x.get("name") or x.get("sku") or "Producto","cost":cost,"currency":x.get("currency") or "EUR","url":x.get("url") or x.get("product_url"),"sku":x.get("sku"),"verified":True,"source":"supplier_catalog"}
                    if cost is not None and sale: row["margin"]=margin(cost,sale,float(x.get("fees") or 0),float(x.get("shipping") or 0))
                    candidates.append(row)
        except Exception as exc:
            holdings.update_company(scope_id,"commerce",error=f"Catálogo proveedor: {exc}")
    if not candidates:
        result=public_search_results(query+" proveedor mayorista precio",limit=10)
        for x in result.get("results") or []:
            blob=(str(x.get("title") or "")+" "+str(x.get("snippet") or ""))
            vals=[]
            for m in _PRICE_RE.finditer(blob):
                try:
                    v=float(m.group(1).replace(",","."))
                    if 0.05 <= v <= 100000: vals.append(v)
                except Exception: pass
            candidates.append({"title":x.get("title") or "Resultado proveedor","cost":min(vals) if vals else None,"currency":"EUR","url":x.get("url"),"verified":False,"source":result.get("provider") or "web","margin":margin(min(vals),sale) if vals and sale else None})
    decision=gate("Seleccionar producto/proveedor para análisis comercial",{"query":query,"sale_price":sale,"candidates":candidates[:10]},"medium")
    holdings.update_company(scope_id,"commerce",action=f"Scouting: {len(candidates)} candidato(s) para «{query}»; sin compras automáticas.",event="SCOUT",event_detail=query)
    return {"ok":True,"query":query,"sale_price":sale,"candidates":candidates[:20],"decision":decision,"purchase_authority":False}
