import json
import os
import re
from html.parser import HTMLParser
from urllib.parse import urlparse, quote_plus

import requests


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style", "noscript", "svg"} and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            t = re.sub(r"\s+", " ", data).strip()
            if t:
                self.parts.append(t)


def _gemini_key():
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    try:
        from .config import load
    except ImportError:
        from config import load
    cfg = load()
    return str(cfg.get("api", {}).get("api_key", "") or "").strip()


def _model():
    env_model = os.environ.get("ZAR_WEB_SEARCH_MODEL", "").strip()
    if env_model:
        return env_model
    try:
        from .config import load
    except ImportError:
        from config import load
    cfg = load()
    return str(cfg.get("api", {}).get("model", "gemini-3.8-flash") or "gemini-3.8-flash").strip()


def _add_citations(text, metadata):
    chunks = metadata.get("groundingChunks") or []
    supports = metadata.get("groundingSupports") or []
    # Insert citations into the model text using the source indexes. Work from the
    # end of the text backwards so character offsets remain valid.
    inserts = []
    for sup in supports:
        seg = sup.get("segment") or {}
        end = seg.get("endIndex")
        if not isinstance(end, int):
            continue
        links = []
        for idx in sup.get("groundingChunkIndices") or []:
            if not isinstance(idx, int) or idx < 0 or idx >= len(chunks):
                continue
            web = chunks[idx].get("web") or {}
            uri = web.get("uri")
            if uri:
                links.append(f"[{idx+1}]({uri})")
        if links:
            inserts.append((end, " " + ", ".join(dict.fromkeys(links))))
    for end, ins in sorted(inserts, key=lambda x: x[0], reverse=True):
        text = text[:end] + ins + text[end:]
    return text



class _SearchResultParser(HTMLParser):
    """Small dependency-free parser for public search result pages."""
    def __init__(self):
        super().__init__()
        self.results = []
        self._current = None
        self._tag = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        cls = (attrs.get("class") or "").lower()
        href = attrs.get("href") or ""
        if tag.lower() == "a" and href and ("result__a" in cls or "b_algo" in cls or "result-title" in cls):
            self._current = {"url": href, "title": "", "snippet": ""}
            self._tag = "a"
            self._text = []
        elif self._current and tag.lower() in {"div", "p", "span"}:
            # Keep collecting text while a result is open.
            pass

    def handle_data(self, data):
        if self._current:
            t = re.sub(r"\s+", " ", data).strip()
            if t:
                self._text.append(t)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._current:
            text = " ".join(self._text).strip()
            if text:
                self._current["title"] = text[:500]
                self.results.append(self._current)
            self._current = None
            self._tag = None
            self._text = []


def _normalise_search_url(url):
    url = (url or "").strip()
    if not url:
        return ""
    # DuckDuckGo may return redirect wrappers. Keep only direct http(s) URLs.
    if url.startswith("//"):
        url = "https:" + url
    # DuckDuckGo redirect wrapper: /l/?uddg=<encoded-url>
    try:
        parsed = urlparse(url)
        if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
            from urllib.parse import parse_qs, unquote
            target = (parse_qs(parsed.query).get("uddg") or [""])[0]
            if target:
                url = unquote(target)
    except Exception:
        pass
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return ""


def _public_search(query, limit=8):
    """Keyless emergency search fallback.

    Primary fallback is DuckDuckGo's HTML result page; Bing's RSS endpoint is a
    second no-key fallback. This is deliberately used only when the grounded
    Gemini search is unavailable, so Zar never becomes dependent on scraping.
    """
    q = (query or "").strip()
    errors = []
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; Zar/27.39; +https://example.invalid)",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.7",
    }
    # DuckDuckGo HTML
    try:
        r = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": q}, headers=headers, timeout=20,
        )
        if r.ok:
            parser = _SearchResultParser(); parser.feed(r.text)
            rows=[]; seen=set()
            for item in parser.results:
                u=_normalise_search_url(item.get("url"))
                if not u or u in seen or "duckduckgo.com" in urlparse(u).netloc:
                    continue
                seen.add(u)
                rows.append({"title": item.get("title") or u, "url": u, "snippet": item.get("snippet", "")})
                if len(rows) >= limit: break
            if rows:
                return {"ok": True, "provider": "DuckDuckGo fallback", "live": True, "query": q, "results": rows}
            errors.append("DuckDuckGo no devolvió resultados parseables")
        else:
            errors.append(f"DuckDuckGo HTTP {r.status_code}")
    except requests.RequestException as exc:
        errors.append(f"DuckDuckGo: {exc}")

    # Bing RSS: useful as a second no-key fallback and easier to parse reliably.
    try:
        r = requests.get(
            "https://www.bing.com/search",
            params={"q": q, "format": "rss", "setlang": "es-ES"},
            headers=headers, timeout=20,
        )
        if r.ok:
            class _RSSParser(HTMLParser):
                def __init__(self):
                    super().__init__(); self.items=[]; self.cur=None; self.tag=None; self.buf=[]
                def handle_starttag(self, tag, attrs):
                    if tag.lower() in {"item","title","link","description"}:
                        if tag.lower()=="item": self.cur={}
                        self.tag=tag.lower(); self.buf=[]
                def handle_data(self,data):
                    if self.cur is not None and self.tag:
                        self.buf.append(data)
                def handle_endtag(self,tag):
                    t=tag.lower()
                    if self.cur is not None and t==self.tag:
                        self.cur[t]=" ".join(self.buf).strip()
                        self.tag=None; self.buf=[]
                    if t=="item" and self.cur:
                        self.items.append(self.cur); self.cur=None
            parser=_RSSParser(); parser.feed(r.text)
            rows=[]; seen=set()
            for item in parser.items:
                u=_normalise_search_url(item.get("link"))
                if not u or u in seen: continue
                seen.add(u); rows.append({"title": item.get("title") or u, "url": u, "snippet": re.sub(r"<[^>]+>", " ", item.get("description", ""))[:1000]})
                if len(rows)>=limit: break
            if rows:
                return {"ok": True, "provider": "Bing RSS fallback", "live": True, "query": q, "results": rows}
            errors.append("Bing RSS no devolvió resultados parseables")
        else:
            errors.append(f"Bing HTTP {r.status_code}")
    except requests.RequestException as exc:
        errors.append(f"Bing: {exc}")

    return {"ok": False, "live": False, "error": "; ".join(errors)[:1600]}


def _brave_search(query, limit=8):
    """Optional structured fallback when BRAVE_SEARCH_API_KEY is configured."""
    key = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
    if not key:
        return None
    try:
        r = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": max(1, min(int(limit), 20)), "country": "ES", "search_lang": "es"},
            headers={"Accept":"application/json", "X-Subscription-Token": key},
            timeout=25,
        )
        if not r.ok:
            return {"ok": False, "live": False, "error": f"Brave Search HTTP {r.status_code}: {r.text[:900]}"}
        data=r.json(); rows=[]
        for x in ((data.get("web") or {}).get("results") or []):
            u=x.get("url")
            if u:
                rows.append({"title":x.get("title") or u, "url":u, "snippet":x.get("description") or ""})
        return {"ok": bool(rows), "live": bool(rows), "provider":"Brave Search fallback", "query":query, "results":rows[:limit], "error": "Brave no devolvió resultados" if not rows else ""}
    except (requests.RequestException, ValueError) as exc:
        return {"ok":False, "live":False, "error":f"Brave Search: {exc}"}


def _fallback_web_search(query, instructions=""):
    brave=_brave_search(query, 8)
    result=brave if brave and brave.get("ok") else _public_search(query, 8)
    if not result.get("ok"):
        return result
    rows=result.get("results") or []
    text=(
        f"Búsqueda web en vivo mediante {result.get('provider','proveedor alternativo')}. "
        "Estos son resultados de búsqueda, no conocimiento interno. Para verificar detalles, abre las URLs con web_open.\n\n"
        + "\n".join(f"[{i+1}] {x['title']} — {x['url']}\n{x.get('snippet','')}" for i,x in enumerate(rows))
    )
    return {"ok":True,"live":True,"provider":result.get("provider"),"query":query,"text":text,"sources":[{"title":x["title"],"url":x["url"]} for x in rows]}


def google_web_search(query, instructions=""):
    """Search the live public web through Gemini Google Search grounding.

    Returns the synthesized answer plus source metadata/citations. This works
    from either the cloud or local Zar agent because the search itself is a
    separate server-side Gemini call.
    """
    query = (query or "").strip()
    if not query:
        return {"ok": False, "error": "Falta la consulta de búsqueda."}
    key = _gemini_key()
    if not key:
        return _fallback_web_search(query, instructions)
    model = _model()
    prompt = (
        "Responde en español y usa Búsqueda de Google para obtener información pública y actualizada. "
        "Prioriza fuentes primarias, oficiales y fiables; contrasta cuando el tema lo requiera. "
        "No inventes datos. Distingue claramente hechos, estimaciones y opiniones. "
        "Incluye enlaces/citas a las fuentes usadas. "
    )
    if instructions:
        prompt += "Instrucciones adicionales del usuario: " + instructions.strip() + "\n"
    prompt += "Consulta: " + query

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.2},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    try:
        r = requests.post(
            url,
            params={"key": key},
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=90,
        )
    except requests.RequestException as exc:
        return {"ok": False, "error": f"No se pudo contactar con la búsqueda web: {exc}"}
    if not r.ok:
        # 429/403/5xx are common quota/provider failures. Fall back to an independent
        # live search instead of making the agent abandon the user request.
        return _fallback_web_search(query, instructions)

    try:
        data = r.json()
        cand = (data.get("candidates") or [{}])[0]
        parts = (cand.get("content") or {}).get("parts") or []
        text = "\n".join(p.get("text", "") for p in parts if p.get("text"))
        metadata = cand.get("groundingMetadata") or {}
        if not text:
            return _fallback_web_search(query, instructions)
        # Strict grounding rule: a successful HTTP response is not enough.
        # Require Google Search grounding metadata, otherwise the model may have
        # answered from its internal knowledge despite the search tool being requested.
        if not (metadata.get("groundingChunks") or metadata.get("webSearchQueries")):
            return _fallback_web_search(query, instructions)
        cited = _add_citations(text, metadata)
        sources = []
        for chunk in metadata.get("groundingChunks") or []:
            web = chunk.get("web") or {}
            uri = web.get("uri")
            title = web.get("title") or uri
            if uri:
                sources.append({"title": title, "url": uri})
        # Preserve order and remove duplicate URLs.
        seen = set(); unique_sources = []
        for s in sources:
            if s["url"] in seen:
                continue
            seen.add(s["url"]); unique_sources.append(s)
        if unique_sources:
            cited += "\n\n**Fuentes**\n" + "\n".join(
                f"- [{s['title']}]({s['url']})" for s in unique_sources[:10]
            )
        return {
            "ok": True,
            "live": True,
            "provider": "Google Search grounding",
            "query": query,
            "text": cited,
            "sources": unique_sources[:10],
            "search_queries": metadata.get("webSearchQueries") or [],
        }
    except Exception as exc:
        return {"ok": False, "error": f"Respuesta de búsqueda no válida: {exc}"}


def fetch_webpage(url, max_chars=18000):
    """Fetch a public webpage and extract readable text for analysis."""
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return {"ok": False, "error": "Solo se permiten URLs http/https."}
    try:
        r = requests.get(
            url,
            timeout=30,
            headers={"User-Agent": "Zar/1.0 (+https://example.invalid)"},
            allow_redirects=True,
        )
        r.raise_for_status()
        parser = _TextParser()
        parser.feed(r.text)
        text = "\n".join(parser.parts)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return {"ok": True, "url": r.url, "status": r.status_code, "text": text[:max_chars]}
    except requests.RequestException as exc:
        return {"ok": False, "error": f"No se pudo abrir la página: {exc}"}


def search_inspiration_images(query, limit=12):
    """Find public image references via Wikimedia Commons for Zar Studio inspiration."""
    q = (query or '').strip()
    if not q:
        return {"ok": False, "error": "Falta una consulta de imágenes."}
    try:
        r = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "generator": "search",
                "gsrsearch": q,
                "gsrnamespace": 6,
                "gsrlimit": max(1, min(int(limit or 12), 24)),
                "prop": "imageinfo",
                "iiprop": "url|extmetadata|mime",
                "iiurlwidth": 640,
                "format": "json",
                "origin": "*",
            },
            timeout=30,
            headers={"User-Agent": "Zar/1.0 inspiration search"},
        )
        r.raise_for_status()
        data = r.json()
        pages = ((data.get("query") or {}).get("pages") or {}).values()
        items = []
        for p in pages:
            info = (p.get("imageinfo") or [{}])[0]
            url = info.get("url")
            thumb = info.get("thumburl") or url
            if not url or not thumb:
                continue
            meta = info.get("extmetadata") or {}
            items.append({
                "title": re.sub(r"^File:", "", p.get("title") or "Imagen"),
                "url": url,
                "thumb_url": thumb,
                "description": ((meta.get("ImageDescription") or {}).get("value") or "")[:800],
                "author": ((meta.get("Artist") or {}).get("value") or "")[:200],
                "source": "Wikimedia Commons",
                "license": ((meta.get("LicenseShortName") or {}).get("value") or "")[:120],
                "page_url": "https://commons.wikimedia.org/wiki/" + (p.get("title") or "").replace(" ", "_"),
            })
        return {"ok": True, "query": q, "items": items}
    except Exception as exc:
        return {"ok": False, "error": f"No se pudieron buscar imágenes de inspiración: {exc}"}


def analyze_inspiration_image(image_url, instructions=""):
    """Download a public image and ask the configured Gemini model to analyze design cues.
    The analysis is advisory: it never changes Zar's source code automatically.
    """
    url = (image_url or '').strip()
    if not url.startswith(('http://', 'https://')):
        return {"ok": False, "error": "URL de imagen no válida."}
    key = _gemini_key()
    if not key:
        return {"ok": False, "error": "No hay GEMINI_API_KEY para analizar la referencia."}
    model = _model()
    try:
        r = requests.get(url, timeout=30, headers={"User-Agent": "Zar/1.0 inspiration analyzer"})
        r.raise_for_status()
        content_type = (r.headers.get('Content-Type') or 'image/jpeg').split(';', 1)[0]
        if not content_type.startswith('image/'):
            return {"ok": False, "error": "La URL no devuelve una imagen."}
        import base64
        b64 = base64.b64encode(r.content).decode('ascii')
        prompt = (
            "Analiza esta referencia visual para un editor multimedia. Devuelve en español una ficha práctica "
            "con: composición, jerarquía, tipografía, paleta, contraste, tratamiento de imagen, movimiento/ritmo "
            "si es deducible, y 5 mejoras concretas que Zar Studio podría incorporar. No copies contenido protegido; "
            "extrae patrones de diseño generales. Si algo no puede inferirse, dilo. "
        )
        if instructions:
            prompt += "Instrucción adicional: " + instructions.strip() + "\n"
        payload = {
            "contents": [{"parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": content_type, "data": b64}},
            ]}],
            "generationConfig": {"temperature": 0.2},
        }
        rr = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": key}, headers={"Content-Type": "application/json"}, json=payload, timeout=90,
        )
        if not rr.ok:
            return {"ok": False, "error": f"Gemini HTTP {rr.status_code}: {rr.text[:1000]}"}
        data = rr.json(); cand=(data.get('candidates') or [{}])[0]
        parts=(cand.get('content') or {}).get('parts') or []
        text='\n'.join(p.get('text','') for p in parts if p.get('text')).strip()
        return {"ok": bool(text), "analysis": text or "No se obtuvo análisis.", "url": url, "model": model}
    except Exception as exc:
        return {"ok": False, "error": f"No se pudo analizar la referencia: {exc}"}
