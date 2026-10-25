"""Bounded public discovery evidence. Discovery is never technical verification."""
import codecs
import json
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit, urljoin

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
        if tag == 'a' and attrs.get('href', '').startswith(('https://','/')) and not attrs.get('href','').startswith('//') and len(self.links) < 40:
            link=attrs['href'][:2000]
            if link not in self.links:self.links.append(link)

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
    visual=str((analysis or {}).get('visual_findings') or '')
    # Exact visible addresses/headers are hints, not verified ownership or research.
    observed=['https://github.com/'+r for r in re.findall(r'\bgithub\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)',visual,re.I)]
    observed+=['https://github.com/'+r for r in re.findall(r'(?<![\w./-])([A-Za-z0-9_-]+/[A-Za-z0-9_.-]+)\s+Public\b',visual,re.I)]
    observed+=['https://'+u for u in re.findall(r'(?<![\w/@.-])((?:[a-z0-9-]+\.)+(?:com|org|ai|app|dev|io|net|co)(?:/[A-Za-z0-9_~./%-]*)?)(?![\w.-])',visual,re.I)]
    urls=list(dict.fromkeys(urls+observed))[:20]
    text+='\nVisible address hints: '+' '.join(observed[:10]) if observed else ''
    if row.get('clarified_project'):
        resolution=row.get('entity_resolution') or {}
        historical_sources=(row.get('research_package') or {}).get('sources',[])
        urls=list(dict.fromkeys(urls+[u for u in resolution.get('sources',[])+historical_sources if isinstance(u,str) and u.startswith('https://')]+[u for u in (resolution.get('website'),) if isinstance(u,str) and u.startswith('https://')]))[:20]
    return {'permalink': row.get('source_url', ''), 'caption': row.get('caption', ''),
            'transcript': (analysis or {}).get('transcript', ''), 'visual_text': (analysis or {}).get('visual_findings', ''),
            'project_names': [row['clarified_project']] if row.get('clarified_project') else (analysis or {}).get('project_names', []), 'text': text,
            'github_urls': [u for u in urls if urlsplit(u).hostname == 'github.com'],
            'outbound_links': [u for u in urls if urlsplit(u).hostname not in ('instagram.com', 'www.instagram.com', 'github.com')],
            'metadata': sanitize(metadata.get('metadata', {})), 'confidence': 'DISCOVERY_ONLY',
            'media_coverage': (analysis or {}).get('input_media', []),
            'path': 'DIRECT_MEDIA' if analysis else 'ZAR_INSTAGRAM_BROWSER_SESSION' if discovery.get('status')=='AUTHENTICATED_DISCOVERY' else 'PUBLIC_BROWSER' if discovery.get('text') else 'PERMALINK_METADATA' if metadata.get('text') else 'TEXT_ONLY'}


def video_parts(content, remaining):
    """At most twelve scene/text-diverse frames and 180 seconds of mono audio."""
    import base64
    import shutil
    import subprocess
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'): return [], {'frames': 0, 'audio': 'NATIVE_VIDEO_INPUT'}
    try:
        probe = subprocess.run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'pipe', '-show_entries', 'format=duration', '-of', 'json', '-i', 'pipe:0'],
                               input=content, capture_output=True, timeout=10)
        duration = float(json.loads(probe.stdout).get('format', {}).get('duration', 0))
        if not 0 < duration <= 180: return [], {'frames': 0, 'audio': 'NATIVE_VIDEO_INPUT', 'duration_limit': True}
        def extract(filter_,limit):
            result=subprocess.run(['ffmpeg','-v','info','-protocol_whitelist','pipe','-i','pipe:0','-vf',filter_+',showinfo,scale=960:1280:force_original_aspect_ratio=decrease',
                '-vsync','vfr','-frames:v',str(limit),'-f','image2pipe','-vcodec','mjpeg','pipe:1'],input=content,capture_output=True,timeout=30)
            images=re.findall(b'\xff\xd8.*?\xff\xd9',result.stdout,re.S)[:limit]
            times=[float(x) for x in re.findall(r'pts_time:([0-9.]+)',result.stderr.decode('utf-8','replace'))]
            return [(image,times[i] if i<len(times) else None) for i,image in enumerate(images)]
        candidates=extract('select=gt(scene\\,0.12)',24)
        if len(candidates)<8:candidates+=extract(f'fps={12/duration}',12)
        from .reel_frames import informative_indices
        chosen=informative_indices([raw for raw,_ in candidates],12)
        parts = []; count = 0;timestamps=[]
        for selected in chosen:
            frame,at=candidates[selected]
            if len(frame) > remaining: break
            remaining -= len(frame); count += 1;timestamps.append(at)
            parts.append({'inlineData': {'mimeType': 'image/jpeg', 'data': base64.b64encode(frame).decode()}})
        audio = subprocess.run(['ffmpeg', '-v', 'error', '-protocol_whitelist', 'pipe', '-i', 'pipe:0', '-t', '180', '-vn', '-ac', '1', '-ar', '16000', '-f', 'wav', 'pipe:1'],
                               input=content, capture_output=True, timeout=20)
        if audio.returncode == 0 and 44 < len(audio.stdout) <= remaining:
            parts.append({'inlineData': {'mimeType': 'audio/wav', 'data': base64.b64encode(audio.stdout).decode()}})
            audio_state = 'EXTRACTED_FULL_BOUNDED_AUDIO'
        else: audio_state = 'NATIVE_VIDEO_INPUT'
        return parts, {'frames': count, 'audio': audio_state, 'duration': duration,'selection':'SCENE_TEXT_DETAIL_NOVELTY','frame_timestamps':timestamps}
    except (OSError, ValueError, subprocess.SubprocessError): return [], {'frames': 0, 'audio': 'NATIVE_VIDEO_INPUT'}


def fetch_official(url):
    """Public HTTPS only; no credentials, scripts, arbitrary redirects or private hosts."""
    from . import browser_network
    import requests
    browser_network.public_url(url); proxy = browser_network.start_proxy()
    original_host=re.sub(r'^(?:www|docs|app)\.', '', urlsplit(url).hostname or '')
    allowed_hosts={original_host,'www.'+original_host,'docs.'+original_host,'app.'+original_host}
    try:
        with requests.Session() as client:
            client.trust_env = False; client.proxies = {'https': 'http://127.0.0.1:' + str(proxy.server_address[1])}
            for hop in range(3):
                with client.get(url, timeout=(5, 15), allow_redirects=False, stream=True) as response:
                    if response.status_code in {301,302,303,307,308}:
                        target=urljoin(url,response.headers.get('Location',''))
                        parsed=urlsplit(target)
                        if hop==2 or parsed.scheme!='https' or parsed.hostname not in allowed_hosts:
                            raise ValueError('OFFICIAL_SOURCE_REDIRECT_REJECTED')
                        browser_network.public_url(target);url=target;continue
                    if response.status_code != 200: raise ValueError('OFFICIAL_SOURCE_UNAVAILABLE')
                    if 'text/html' not in response.headers.get('Content-Type', ''): raise ValueError('OFFICIAL_SOURCE_UNSUPPORTED')
                    result = parse_chunks(response.iter_content(32768), stop_at_head=False);break
        result['outbound_links']=list(dict.fromkeys(urljoin(url,u) for u in result.get('outbound_links',[]) if urljoin(url,u).startswith('https://')))
        return {'url': url, 'title': result.get('title'), 'description': result.get('description') or result.get('og:description'),
                'text': result['text'], 'metadata': result, 'verified': True}
    finally: proxy.shutdown(); proxy.server_close()


def service_resolution(discovery_evidence):
    """A named hint chooses a candidate; official cross-links must corroborate it."""
    from .reposnews_inbox import clean_url
    names = [str(x).strip() for x in discovery_evidence.get('project_names', []) if isinstance(x,str)]
    links = [clean_url(u) for u in discovery_evidence.get('outbound_links', [])]
    links = [u for u in links if u and not re.search(r'github|fbcdn|cdninstagram|lookaside|youtube|tiktok|facebook|twitter|linkedin|(^|\.)x\.com$', urlsplit(u).hostname or '', re.I)]
    if not links and len(set(names))==1:
        from .web_search import public_search_results
        result=public_search_results(names[0]+' official website documentation',limit=4)
        links=[clean_url(r.get('url') or '') for r in result.get('results',[])][:4]
        normal=lambda s:re.sub(r'[^a-z0-9]','',s.casefold())
        links=[u for u in links if u and normal(names[0]) in normal(urlsplit(u).hostname or '')]
    def base_host(u): return re.sub(r'^(?:www|docs|app)\.', '', urlsplit(u).hostname or '')
    if len({base_host(u) for u in links})>1 and len(set(names))==1:
        normal=lambda s:re.sub(r'[^a-z0-9]','',s.casefold())
        hosts={base_host(u) for u in links if normal(names[0]) in normal(base_host(u))}
        if len(hosts)==1:links=[u for u in links if base_host(u) in hosts]
    if len({base_host(u) for u in links})>1 and len(set(names))==1:
        # Search mirrors do not make the real project unknowable: require the
        # website -> repository -> canonical homepage chain, never a popularity rank.
        from . import reposnews
        import requests
        confirmed={}
        for candidate_host in list(dict.fromkeys(base_host(u) for u in links))[:3]:
            group=[u for u in links if base_host(u)==candidate_host]
            try:
                candidate=service_resolution(dict(discovery_evidence,outbound_links=group))
                if not candidate or candidate.get('type')!='REPOSITORY':continue
                metadata=reposnews.github('repos/'+candidate['repo'])
                if metadata.get('fork') or metadata.get('archived') or metadata.get('private'):continue
                if base_host(metadata.get('homepage') or '')!=base_host(candidate['website']):continue
                confirmed[candidate['repo'].casefold()]=candidate
            except (ValueError,OSError,requests.RequestException) as exc:
                if getattr(exc,'http_status',None) in {403,429}:raise
        return next(iter(confirmed.values())) if len(confirmed)==1 else None
    if len({base_host(u) for u in links}) != 1:return None
    roots=[u for u in links if (urlsplit(u).hostname or '').removeprefix('www.')==base_host(u)]
    if not roots:return None
    parsed=urlsplit(roots[0]);website='https://'+parsed.netloc+'/'
    docs=next((u for u in links if (urlsplit(u).hostname or '').startswith('docs.')), '')
    name=names[0] if len(set(names))==1 else ''
    site = fetch_official(website)
    if not name:name=(site.get('title') or '').split('|')[0].strip()[:100]
    normalize=lambda s:re.sub(r'[^a-z0-9]','',s.casefold())
    repository_links=site.get('metadata',{}).get('outbound_links',[])+re.findall(r'https://github\.com/[^\s<>"\'\\]+',site['text'])
    repositories=set()
    for link in repository_links:
        parsed=urlsplit(link);parts=parsed.path.strip('/').split('/')
        if parsed.hostname=='github.com' and len(parts)==2 and re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+','/'.join(parts)) and normalize(parts[-1])==normalize(name):repositories.add('/'.join(parts))
    if len(repositories)==1:
        repo=next(iter(repositories))
        return {'status':'RESOLVED','type':'REPOSITORY','repo':repo,'name':name,'website':site['url'],'confidence':'OFFICIAL_WEBSITE_REPOSITORY_LINK','sources':[site['url'],'https://github.com/'+repo]}
    if not docs:
        host = urlsplit(website).hostname.removeprefix('www.')
        match = re.search(r'https://docs\.' + re.escape(host) + r'[^\s<>"\'\\]*', site['text'])
        if match: docs = clean_url(match.group())
        else:
            docs = next((clean_url(u) for u in site.get('metadata', {}).get('outbound_links', [])
                         if urlsplit(u).hostname in (host, 'www.' + host) and re.search(r'^/(docs|documentation|developers)(/|$)', urlsplit(u).path)), '')
        if not docs: return None
        name = (site.get('title') or '').split('|')[0].strip()[:100]
    host = urlsplit(website).hostname.removeprefix('www.')
    def linked_hosts(page):
        links = page.get('metadata', {}).get('outbound_links', []) + re.findall(r'https://[^\s<>"\'\\]+', page['text'])
        return {urlsplit(u).hostname for u in links}
    if urlsplit(docs).hostname not in linked_hosts(site):
        bridge=next((u for u in site.get('metadata',{}).get('outbound_links',[]) if urlsplit(u).hostname in {host,'www.'+host} and re.match(r'^/(docs|documentation|developers)(/|$)',urlsplit(u).path)),None)
        if not bridge:return None
        doc=fetch_official(bridge)
        if urlsplit(doc['url']).hostname!=urlsplit(docs).hostname:return None
        docs=bridge  # The site's own link and its checked HTTP chain prove the forward link.
    else:doc=fetch_official(docs)
    if not name or not linked_hosts(doc).intersection({host, 'www.' + host}) or urlsplit(docs).hostname not in linked_hosts(site): return None
    return {'status': 'RESOLVED', 'type': 'SERVICE', 'name': name, 'website': site['url'], 'docs': doc['url'],
            'confidence': 'OFFICIAL_SITE_DOCS_CROSSLINK', 'sources': [site['url'], doc['url']], 'verified_pages': [site, doc]}


def research_service(resolution):
    from . import holdings
    from .reposnews_inbox import safe_caption, clean_url
    pages = list(resolution['verified_pages'])
    host = urlsplit(resolution['website']).hostname.removeprefix('www.')
    extra = [u for u in pages[0].get('metadata', {}).get('outbound_links', [])
             if urlsplit(u).hostname in (host, 'www.' + host) and re.search(r'/pricing|/terms|/api', urlsplit(u).path)][:3]
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
