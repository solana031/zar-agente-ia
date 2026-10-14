"""Bounded public discovery evidence. Discovery is never technical verification."""
import codecs
import json
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

MAX_HTML = 2 * 1024 * 1024
SECRET = re.compile(r'token|cookie|password|secret|auth|credential|session|api.?key', re.I)


class MetadataParser(HTMLParser):
    def __init__(self, shortcode=None):
        super().__init__()
        self.meta = {}
        self.title = ''
        self.visible = ''
        self.capture = False
        self.skip = 0
        self.script = None
        self.script_text = ''
        self.structured = []
        self.links = []
        self.shortcode = shortcode
        self.media = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'title': self.capture = True
        if tag in ('script', 'style', 'noscript'): self.skip += 1
        if tag == 'script' and attrs.get('type') in ('application/ld+json', 'application/json'):
            self.script = attrs['type']; self.script_text = ''
        if tag == 'meta':
            key = attrs.get('property') or attrs.get('name')
            if key in ('description', 'og:title', 'og:description', 'og:image', 'og:video', 'og:video:url', 'twitter:description', 'author'):
                self.meta[key] = attrs.get('content', '')[:6000]
        if tag == 'link' and attrs.get('rel') == 'canonical': self.meta['canonical'] = attrs.get('href', '')[:2000]
        if tag == 'a' and attrs.get('href', '').startswith('https://') and len(self.links) < 40:
            self.links.append(attrs['href'][:2000])

    def handle_endtag(self, tag):
        if tag == 'title': self.capture = False
        if tag == 'script' and self.script:
            try:
                value = json.loads(self.script_text)
                if self.script == 'application/json': value = self.target_node(value)
                if value:
                    self.structured.append(sanitize(value))
                    self.collect_media(value)
            except ValueError: pass
            self.structured = self.structured[:4]; self.script = None
        if tag in ('script', 'style', 'noscript'): self.skip = max(0, self.skip - 1)

    def handle_data(self, text):
        if self.capture: self.title = (self.title + text)[:1000]
        elif self.script: self.script_text = (self.script_text + text)[:64000]
        elif not self.skip: self.visible = (self.visible + ' ' + text.strip())[:10000]

    def result(self):
        return {**self.meta, 'title': self.title, 'visible_text': self.visible,
                'json_ld': self.structured, 'text': ' '.join([self.title, self.meta.get('description', ''),
                self.meta.get('og:title', ''), self.meta.get('og:description', ''), self.visible,
                json.dumps(self.structured, ensure_ascii=False) if self.structured else '', ' '.join(self.links)]).strip()[:24000], 'outbound_links': self.links, 'media_refs': self.media}

    def target_node(self, value, depth=0):
        if not self.shortcode or depth > 8: return None
        if isinstance(value, dict):
            if value.get('shortcode') == self.shortcode:
                return {k: value[k] for k in ('caption', 'title', 'description', 'owner', 'video_url', 'display_url', 'shortcode') if k in value}
            for child in list(value.values())[:30]:
                found = self.target_node(child, depth + 1)
                if found: return found
        elif isinstance(value, list):
            for child in value[:10]:
                found = self.target_node(child, depth + 1)
                if found: return found
        return None

    def collect_media(self, value, depth=0):
        if depth > 4 or len(self.media) >= 10: return
        if isinstance(value, dict):
            for key, child in list(value.items())[:30]:
                if key in ('contentUrl', 'video_url', 'thumbnailUrl', 'display_url') and isinstance(child, str) and child.startswith('https://'):
                    self.media.append({'type': 'image' if key in ('thumbnailUrl', 'display_url') else 'video', 'url': child[:6000]})
                elif isinstance(child, (dict, list)): self.collect_media(child, depth + 1)
        elif isinstance(value, list):
            for child in value[:10]: self.collect_media(child, depth + 1)


def parse_chunks(chunks, limit=MAX_HTML, stop_at_head=True, shortcode=None):
    """Incremental parsing retains useful head metadata even when the body is huge."""
    parser = MetadataParser(shortcode); decoder = codecs.getincrementaldecoder('utf-8')('replace'); used = 0
    for chunk in chunks:
        piece = chunk[:max(0, limit - used)]; used += len(piece)
        parser.feed(decoder.decode(piece))
        if stop_at_head and parser.meta.get('og:description') and parser.meta.get('og:title') and ('</head>' in piece.decode('utf-8', 'ignore').lower()): break
        if used >= limit: break
    parser.feed(decoder.decode(b'', final=True))
    result = parser.result(); result['bytes_scanned'] = used; result['scan_limited'] = used >= limit
    return result


def sanitize(value, depth=0):
    from .reposnews_inbox import safe_caption, clean_url
    if depth > 6: return None
    if isinstance(value, dict):
        return {str(k)[:80]: sanitize(v, depth + 1) for k, v in list(value.items())[:30] if not SECRET.search(str(k))}
    if isinstance(value, list): return [sanitize(x, depth + 1) for x in value[:12]]
    if isinstance(value, str):
        if value.startswith('https://'): return clean_url(value)
        text = safe_caption(value)[:3000]
        return re.sub(r'\b(?:eyJ[A-Za-z0-9_.-]{30,}|sk-[A-Za-z0-9_-]{15,}|AIza[A-Za-z0-9_-]{20,})\b', '[REDACTED]', text)
    return value if isinstance(value, (int, float, bool)) or value is None else None


def attachment_refs(attachments):
    refs = []
    def visit(value, kind='', depth=0):
        if depth > 4 or len(refs) >= 10: return
        if isinstance(value, list):
            for child in value[:10]: visit(child, kind, depth + 1)
        elif isinstance(value, dict):
            kind = str(value.get('type') or kind)[:30]
            for key, child in list(value.items())[:30]:
                if SECRET.search(str(key)): continue
                if key in ('url', 'src', 'media_url', 'image_url', 'video_url', 'audio_url') and isinstance(child, str):
                    try: parsed = urlsplit(child)
                    except ValueError: continue
                    host = parsed.hostname or ''
                    if parsed.scheme == 'https' and not parsed.username and not parsed.password and (host.endswith(('.fbcdn.net', '.cdninstagram.com')) or host == 'lookaside.fbsbx.com'):
                        refs.append({'type': 'image' if key == 'image_url' else 'video' if key == 'video_url' else kind, 'url': child[:6000]})
                elif isinstance(child, (dict, list)): visit(child, kind, depth + 1)
    visit(attachments)
    return refs[:10]


def evidence(row, analysis, discovery, metadata):
    from .reposnews_inbox import safe_caption
    def clues(value):
        if isinstance(value, dict): return ' '.join(clues(v) for v in value.values())
        if isinstance(value, list): return ' '.join(clues(v) for v in value)
        if not isinstance(value, str) or value.lower() in ('share', 'video', 'audio', 'image', 'carousel', 'text', 'message'): return ''
        if value.startswith('https://'):
            host = urlsplit(value).hostname or ''
            if host in ('instagram.com', 'www.instagram.com', 'lookaside.fbsbx.com') or host.endswith(('.fbcdn.net', '.cdninstagram.com')): return ''
        return value
    pieces = [row.get('caption', ''), clues(row.get('discovery_metadata', {})),
              clues(analysis or {}), discovery.get('text', ''), metadata.get('text', '')]
    text = safe_caption(' '.join(pieces))
    urls = list(dict.fromkeys(re.findall(r'https://[^\s<>"\'\\]+', text)))[:20]
    return {'permalink': row.get('source_url', ''), 'caption': row.get('caption', ''),
            'transcript': (analysis or {}).get('transcript', ''), 'visual_text': (analysis or {}).get('visual_findings', ''),
            'project_names': (analysis or {}).get('project_names', []), 'text': text,
            'github_urls': [u for u in urls if urlsplit(u).hostname == 'github.com'],
            'outbound_links': [u for u in urls if urlsplit(u).hostname not in ('instagram.com', 'www.instagram.com', 'github.com')],
            'metadata': sanitize(metadata.get('metadata', {})), 'confidence': 'DISCOVERY_ONLY',
            'media_coverage': (analysis or {}).get('input_media', []),
            'path': 'DIRECT_MEDIA' if analysis else 'ZAR_INSTAGRAM_BROWSER_SESSION' if discovery.get('status')=='AUTHENTICATED_DISCOVERY' else 'PUBLIC_BROWSER' if discovery.get('text') else 'PERMALINK_METADATA' if metadata.get('text') else 'TEXT_ONLY'}


def bland_hint(text):
    return bool(re.search(r'\bBland\s*AI\b|\bbland\.ai\b', text, re.I) or
                re.search(r'\bAgent Phone Plan\b', text, re.I) and re.search(r'Claude|Codex|Bland', text, re.I))


def video_parts(content, remaining):
    """At most six distributed frames and 180 seconds of mono audio, in memory."""
    import base64
    import shutil
    import subprocess
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'): return [], {'frames': 0, 'audio': 'NATIVE_VIDEO_INPUT'}
    try:
        probe = subprocess.run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'pipe', '-show_entries', 'format=duration', '-of', 'json', '-i', 'pipe:0'],
                               input=content, capture_output=True, timeout=10)
        duration = float(json.loads(probe.stdout).get('format', {}).get('duration', 0))
        if not 0 < duration <= 180: return [], {'frames': 0, 'audio': 'NATIVE_VIDEO_INPUT', 'duration_limit': True}
        frames = subprocess.run(['ffmpeg', '-v', 'error', '-protocol_whitelist', 'pipe', '-i', 'pipe:0', '-vf',
                                 f'fps={6 / duration},scale=640:360:force_original_aspect_ratio=decrease',
                                 '-frames:v', '6', '-f', 'image2pipe', '-vcodec', 'mjpeg', 'pipe:1'],
                                input=content, capture_output=True, timeout=20)
        parts = []; count = 0
        for frame in re.findall(b'\xff\xd8.*?\xff\xd9', frames.stdout, re.S)[:6]:
            if len(frame) > remaining: break
            remaining -= len(frame); count += 1
            parts.append({'inlineData': {'mimeType': 'image/jpeg', 'data': base64.b64encode(frame).decode()}})
        audio = subprocess.run(['ffmpeg', '-v', 'error', '-protocol_whitelist', 'pipe', '-i', 'pipe:0', '-t', '180', '-vn', '-ac', '1', '-ar', '16000', '-f', 'wav', 'pipe:1'],
                               input=content, capture_output=True, timeout=20)
        if audio.returncode == 0 and 44 < len(audio.stdout) <= remaining:
            parts.append({'inlineData': {'mimeType': 'audio/wav', 'data': base64.b64encode(audio.stdout).decode()}})
            audio_state = 'EXTRACTED_FULL_BOUNDED_AUDIO'
        else: audio_state = 'NATIVE_VIDEO_INPUT'
        return parts, {'frames': count, 'audio': audio_state, 'duration': duration}
    except (OSError, ValueError, subprocess.SubprocessError): return [], {'frames': 0, 'audio': 'NATIVE_VIDEO_INPUT'}


def fetch_official(url):
    """Public HTTPS only; no credentials, scripts, arbitrary redirects or private hosts."""
    from . import browser_network
    import requests
    browser_network.public_url(url); proxy = browser_network.start_proxy()
    try:
        with requests.Session() as client:
            client.trust_env = False; client.proxies = {'https': 'http://127.0.0.1:' + str(proxy.server_address[1])}
            with client.get(url, timeout=(5, 15), allow_redirects=False, stream=True) as response:
                if response.status_code != 200: raise ValueError('OFFICIAL_SOURCE_UNAVAILABLE')
                if 'text/html' not in response.headers.get('Content-Type', ''): raise ValueError('OFFICIAL_SOURCE_UNSUPPORTED')
                result = parse_chunks(response.iter_content(32768), stop_at_head=False)
        return {'url': url, 'title': result.get('title'), 'description': result.get('description') or result.get('og:description'),
                'text': result['text'], 'metadata': result, 'verified': True}
    finally: proxy.shutdown(); proxy.server_close()


def service_resolution(discovery_evidence):
    """A named hint chooses a candidate; official cross-links must corroborate it."""
    from .reposnews_inbox import clean_url
    names = {str(x).casefold() for x in discovery_evidence.get('project_names', [])}
    if bland_hint(discovery_evidence['text']) or names in ({'bland'}, {'bland ai'}, {'bland.ai'}):
        website = 'https://www.bland.ai/'; docs = 'https://docs.bland.ai/integrations/mcp/overview'; name = 'Bland AI'
    else:
        links = [clean_url(u) for u in discovery_evidence.get('outbound_links', [])]
        links = [u for u in links if u and not re.search(r'fbcdn|cdninstagram|lookaside|youtube|tiktok|facebook|twitter|linkedin|(^|\.)x\.com$', urlsplit(u).hostname or '', re.I)]
        def base_host(u): return re.sub(r'^(?:www|docs|app)\.', '', urlsplit(u).hostname or '')
        if len({base_host(u) for u in links}) != 1: return None
        roots = [u for u in links if (urlsplit(u).hostname or '').removeprefix('www.') == base_host(u)]
        if not roots: return None
        parsed = urlsplit(roots[0]); website = 'https://' + parsed.netloc + '/'; docs = ''; name = ''
    site = fetch_official(website)
    if not docs:
        host = urlsplit(website).hostname.removeprefix('www.')
        match = re.search(r'https://docs\.' + re.escape(host) + r'[^\s<>"\'\\]*', site['text'])
        if match: docs = clean_url(match.group())
        else:
            docs = next((clean_url(u) for u in site.get('metadata', {}).get('outbound_links', [])
                         if urlsplit(u).hostname in (host, 'www.' + host) and re.search(r'^/(docs|documentation|developers)(/|$)', urlsplit(u).path)), '')
        if not docs: return None
        name = (site.get('title') or '').split('|')[0].strip()[:100]
    doc = fetch_official(docs)
    host = urlsplit(website).hostname.removeprefix('www.')
    def linked_hosts(page):
        links = page.get('metadata', {}).get('outbound_links', []) + re.findall(r'https://[^\s<>"\'\\]+', page['text'])
        return {urlsplit(u).hostname for u in links}
    if not name or not linked_hosts(doc).intersection({host, 'www.' + host}) or urlsplit(docs).hostname not in linked_hosts(site): return None
    return {'status': 'RESOLVED', 'type': 'SERVICE', 'name': name, 'website': website, 'docs': docs,
            'confidence': 'OFFICIAL_SITE_DOCS_CROSSLINK', 'sources': [website, docs], 'verified_pages': [site, doc]}


def research_service(resolution):
    from . import holdings
    from .reposnews_inbox import safe_caption, clean_url
    pages = list(resolution['verified_pages'])
    if resolution['website'] == 'https://www.bland.ai/':
        extra = ['https://app.bland.com/agent-phone-plan', 'https://app.bland.com/agent-phone-plan/agents']
    else:
        host = urlsplit(resolution['website']).hostname.removeprefix('www.')
        extra = [u for u in pages[0].get('metadata', {}).get('outbound_links', [])
                 if urlsplit(u).hostname in (host, 'www.' + host) and re.search(r'/pricing|/terms', urlsplit(u).path)][:2]
    for url in extra[:2]:
        try: pages.append(fetch_official(url))
        except (OSError, ValueError): pass
    return {'repo': resolution['name'], 'entity_type': 'SERVICE', 'metadata': {'homepage': resolution['website'],
            'language': 'API / Service', 'license': 'Commercial service; see official terms'},
            'readme': safe_caption('\n'.join(p['text'] for p in pages)), 'release': None,
            'sources': [p['url'] for p in pages], 'verified_at': holdings._now(), 'official_docs': resolution['docs'],
            'description': pages[0].get('description') or '', 'name': resolution['name'],
            'images': [{'url': clean_url(p.get('metadata', {}).get('og:image')), 'source': p['url']} for p in pages if p.get('metadata', {}).get('og:image')]}


def official_image(package):
    """One bounded raster from an official source; no scripts/SVG or license guess."""
    import hashlib
    import io
    from PIL import Image
    import requests
    from . import browser_network, reposnews
    from .reposnews_inbox import clean_url
    candidates = package.get('images', [])[:1]
    if not candidates: return {}
    image = candidates[0]; url = image['url']; proxy = None
    try:
        browser_network.public_url(url); proxy = browser_network.start_proxy()
        with requests.Session() as client:
            client.trust_env = False; client.proxies = {'https': 'http://127.0.0.1:' + str(proxy.server_address[1])}
            with client.get(url, timeout=(5, 15), stream=True, allow_redirects=False) as response:
                if response.status_code != 200 or response.headers.get('Content-Type', '').split(';')[0] not in ('image/png', 'image/jpeg', 'image/webp'): return {}
                content = bytearray()
                for chunk in response.iter_content(32768):
                    content.extend(chunk)
                    if len(content) > 2000000: return {}
        with Image.open(io.BytesIO(content)) as raster:
            if raster.width * raster.height > 4000000: return {}
            raster.load(); raster = raster.convert('RGB'); raster.thumbnail((1200, 630))
            asset = 'source-' + hashlib.sha256(content).hexdigest()[:24] + '.png'
            folder = reposnews._path().parent / 'media'; folder.mkdir(parents=True, exist_ok=True)
            raster.save(folder / asset, format='PNG')
        return {'image_asset': asset, 'image_kind': 'OFFICIAL_SOURCE_RASTER', 'image_source': clean_url(image['source']),
                'image_license': 'NOT_CONFIRMED', 'image_attribution': 'Visual: ' + clean_url(image['source']) + ' · license not confirmed'}
    except (Image.DecompressionBombError, OSError, ValueError, requests.RequestException): return {}
    finally:
        if proxy: proxy.shutdown(); proxy.server_close()
