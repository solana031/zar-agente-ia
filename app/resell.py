"""ZAR Resell local-first domain layer.

No marketplace credentials or private APIs are used here. The initial 33.4 candidate
ships a demo/readiness adapter so UI and negotiation flows can be validated safely.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json, os, threading, uuid

_LOCK = threading.RLock()
_DATA_DIR = Path(os.environ.get("ZAR_DATA_DIR", Path.home()/".zar"/"data"))
_STORE = _DATA_DIR / "resell.json"

DEMO_ITEMS = [
    {"id":"v-101","platform":"Vinted","mine":True,"title":"Nike Air Max 95","price":80.0,"location":"Majadahonda, Madrid","image":"","favorites":7,"messages":2,"offers":1,"managed":True,"min_price":60.0},
    {"id":"w-202","platform":"Wallapop","mine":True,"title":"Chaqueta The North Face","price":95.0,"location":"Madrid","image":"","favorites":4,"messages":1,"offers":0,"managed":True,"min_price":72.0},
    {"id":"v-303","platform":"Vinted","mine":False,"title":"Adidas Campus 00s","price":42.0,"location":"Pozuelo de Alarcón, Madrid","image":"","favorites":18,"messages":0,"offers":0,"managed":False},
    {"id":"w-404","platform":"Wallapop","mine":False,"title":"iPhone 13 128 GB","price":315.0,"location":"Las Rozas, Madrid","image":"","favorites":31,"messages":0,"offers":0,"managed":False},
    {"id":"v-505","platform":"Vinted","mine":False,"title":"Sudadera Carhartt WIP","price":36.0,"location":"Madrid","image":"","favorites":11,"messages":0,"offers":0,"managed":False},
]
DEMO_EVENTS = [
    {"id":"e-fav","kind":"favorite","platform":"Vinted","item_id":"v-101","title":"Nike Air Max 95","listed_price":80.0,"suggested_offer":72.0,"created_at":"Ahora","status":"pending"},
    {"id":"e-offer","kind":"offer","platform":"Vinted","item_id":"v-101","title":"Nike Air Max 95","listed_price":80.0,"offer":60.0,"suggested_counter":70.0,"created_at":"Hace 7 min","status":"pending"},
]

def _default():
    return {"items": DEMO_ITEMS, "events": DEMO_EVENTS, "history": [], "connectors": [
        {"platform":"Vinted","status":"NOT_CONFIGURED","mode":"demo","detail":"Cuenta real no conectada. Favoritos/ofertas reales pendientes de una vía permitida por la plataforma."},
        {"platform":"Wallapop","status":"NOT_CONFIGURED","mode":"demo","detail":"Cuenta real no conectada. Catálogo y eventos reales pendientes de conector autorizado."},
    ]}

def _read():
    with _LOCK:
        try:
            if _STORE.exists(): return json.loads(_STORE.read_text(encoding="utf-8"))
        except Exception: pass
        return _default()

def _write(data):
    with _LOCK:
        _STORE.parent.mkdir(parents=True, exist_ok=True)
        tmp=_STORE.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(_STORE)

def state(): return _read()

def reset_demo():
    data=_default(); _write(data); return data

def act(event_id, action, amount=None):
    data=_read(); event=next((e for e in data['events'] if e['id']==event_id),None)
    if not event: raise ValueError('Evento no encontrado')
    allowed={'ignore','prepare_offer','accept','reject','counter'}
    if action not in allowed: raise ValueError('Acción no permitida')
    if action in {'prepare_offer','counter'}:
        try: amount=float(amount)
        except Exception: raise ValueError('Importe no válido')
        if amount <= 0: raise ValueError('Importe no válido')
    # 33.4 candidate is deliberately local simulation only: never calls a marketplace.
    event['status']='simulated_'+action
    record={"id":str(uuid.uuid4()),"event_id":event_id,"action":action,"amount":amount,"mode":"SIMULATION","created_at":datetime.now(timezone.utc).isoformat()}
    data['history'].insert(0,record); _write(data)
    return {"ok":True,"simulated":True,"record":record,"event":event}
