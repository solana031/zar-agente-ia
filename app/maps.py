import os
from urllib.parse import quote
import requests

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"


def _key(cfg=None):
    if cfg and cfg.get("maps", {}).get("api_key"):
        return cfg["maps"]["api_key"].strip()
    return os.environ.get("ZAR_MAPS_API_KEY", "").strip()


def maps_status(cfg=None):
    k = _key(cfg)
    return {"ok": bool(k), "configured": bool(k), "message": "Google Maps configurado." if k else "Falta ZAR_MAPS_API_KEY."}


def maps_search_text(query, max_results=5, cfg=None):
    k = _key(cfg)
    if not k:
        return {"ok": False, "error": "Google Maps no está configurado. Falta ZAR_MAPS_API_KEY."}
    body = {"textQuery": query, "pageSize": max(1, min(int(max_results), 10)), "languageCode": "es", "regionCode": "ES"}
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": k,
        "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.googleMapsUri,places.location,places.rating,places.userRatingCount",
    }
    r = requests.post(PLACES_URL, json=body, headers=headers, timeout=30)
    if not r.ok:
        raise RuntimeError(f"Google Places {r.status_code}: {r.text[:1000]}")
    places = []
    for p in (r.json().get("places") or []):
        loc = p.get("location") or {}
        places.append({
            "id": p.get("id", ""),
            "name": (p.get("displayName") or {}).get("text", ""),
            "address": p.get("formattedAddress", ""),
            "maps_url": p.get("googleMapsUri", ""),
            "lat": loc.get("latitude"),
            "lng": loc.get("longitude"),
            "rating": p.get("rating"),
            "reviews": p.get("userRatingCount"),
        })
    return {"ok": True, "query": query, "places": places}


def maps_search_url(query):
    return f"https://www.google.com/maps/search/?api=1&query={quote(query)}"


def maps_directions_url(destination, origin=""):
    base = "https://www.google.com/maps/dir/?api=1"
    if origin:
        base += f"&origin={quote(origin)}"
    base += f"&destination={quote(destination)}"
    return base


def maps_route(origin, destination, travel_mode="DRIVE", cfg=None):
    k = _key(cfg)
    if not k:
        return {"ok": False, "error": "Google Maps no está configurado. Falta ZAR_MAPS_API_KEY.", "maps_url": maps_directions_url(destination, origin)}
    mode = (travel_mode or "DRIVE").upper()
    if mode not in {"DRIVE", "WALK", "BICYCLE", "TWO_WHEELER", "TRANSIT"}:
        mode = "DRIVE"
    body = {
        "origin": {"address": origin},
        "destination": {"address": destination},
        "travelMode": mode,
        "routingPreference": "TRAFFIC_AWARE" if mode == "DRIVE" else None,
        "computeAlternativeRoutes": False,
        "languageCode": "es",
        "units": "METRIC",
    }
    body = {k2:v for k2,v in body.items() if v is not None}
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": k,
        "X-Goog-FieldMask": "routes.duration,routes.distanceMeters,routes.distanceMeters,routes.legs.steps",
    }
    r = requests.post(ROUTES_URL, json=body, headers=headers, timeout=30)
    if not r.ok:
        raise RuntimeError(f"Google Routes {r.status_code}: {r.text[:1000]}")
    routes = r.json().get("routes") or []
    if not routes:
        return {"ok": False, "error": "Google Maps no ha encontrado una ruta.", "maps_url": maps_directions_url(destination, origin)}
    route = routes[0]
    distance = route.get("distanceMeters")
    duration = route.get("duration", "")
    seconds = None
    if isinstance(duration, str) and duration.endswith("s"):
        try: seconds = float(duration[:-1])
        except Exception: pass
    return {
        "ok": True,
        "origin": origin,
        "destination": destination,
        "travel_mode": mode,
        "distance_m": distance,
        "distance_km": round(distance/1000, 2) if isinstance(distance, (int,float)) else None,
        "duration_seconds": seconds,
        "duration": duration,
        "maps_url": maps_directions_url(destination, origin),
    }
