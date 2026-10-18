"""Local Instagram worker: fixed jobs only, dedicated profile, outbound HTTPS."""
import argparse
from contextlib import contextmanager
import http.cookiejar
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import multiprocessing
import queue
import threading
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import requests
from .scoped_http import BearerAuth

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / '.local' / 'instagram-worker'
PROFILE = LOCAL / 'ZAR Instagram Browser Profile'
ACCOUNT = 'zaragente031'
MAX_BYTES = 25 * 1024 * 1024


def reel_url(value):
    # Kept independent from Flask/server imports in the local runtime.
    u = urlsplit(value)
    if (len(value) > 2048 or u.scheme != 'https' or u.netloc not in {'instagram.com', 'www.instagram.com'}
            or not re.fullmatch(r'/(?:reel|p)/[A-Za-z0-9_-]+/?', u.path)):
        raise ValueError('INVALID_INSTAGRAM_URL')
    return 'https://www.instagram.com'+u.path.rstrip('/')+'/'


def media_url(value):
    u = urlsplit(value)
    host = u.hostname or ''
    if u.scheme != 'https' or u.username or u.password or u.port not in (None, 443) or not host.endswith(('.cdninstagram.com', '.fbcdn.net')):
        raise ValueError('INVALID_MEDIA_ORIGIN')
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('INVALID_MEDIA_ADDRESS')
    return value


def run(args, timeout=60):
    return subprocess.run(args, capture_output=True, timeout=timeout, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def validate_video(path):
    if not path.is_file() or not 12 < path.stat().st_size <= MAX_BYTES:
        raise ValueError('MEDIA_SIZE_INVALID')
    with path.open('rb') as f:
        if f.read(8)[4:] != b'ftyp':
            raise ValueError('MP4_REQUIRED')
    probe = run([ffmpeg(), '-hide_banner', '-protocol_whitelist', 'file,pipe', '-i', str(path)], 15)
    info = probe.stderr.decode(errors='replace')
    duration = re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)', info)
    if not duration or 'Video:' not in info:
        raise ValueError('MEDIA_INVALID')
    h, m, s = map(float, duration.groups())
    seconds = h*3600+m*60+s
    if not 0 < seconds <= 180:
        raise ValueError('DURATION_LIMIT')
    return {'duration': seconds, 'audio': 'Audio:' in info}


def download(url, target):
    media_url(url)
    with requests.Session() as client:
        client.trust_env = False
        with client.get(url, stream=True, timeout=(5, 20), allow_redirects=False) as response:
            if response.status_code != 200 or response.headers.get('Content-Type', '').split(';')[0] not in {'video/mp4', 'video/x-m4v'}:
                raise ValueError('MEDIA_TYPE_INVALID')
            total = 0
            deadline = time.monotonic()+45
            with target.open('wb') as f:
                for chunk in response.iter_content(65536):
                    total += len(chunk)
                    if total > MAX_BYTES or time.monotonic() > deadline:
                        raise ValueError('MEDIA_LIMIT')
                    f.write(chunk)
    validate_video(target)
    return target


def cookie_jar(context, directory):
    jar = http.cookiejar.MozillaCookieJar(str(directory/'cookies.txt'))
    for c in context.cookies(['https://www.instagram.com/']):
        if c['domain'].lstrip('.') != 'instagram.com':
            continue
        jar.set_cookie(http.cookiejar.Cookie(0, c['name'], c['value'], None, False, c['domain'],
            c['domain'].startswith('.'), c['domain'].startswith('.'), c['path'], True, c['secure'],
            int(c['expires']) if c.get('expires', -1) > 0 else None, False, None, None, {}, False))
    jar.save(ignore_discard=True, ignore_expires=True)
    os.chmod(jar.filename, 0o600)
    return Path(jar.filename)


def ytdlp(url, directory, cookies=None):
    target = directory/'yt-media.mp4'
    command = [sys.executable, '-m', 'yt_dlp', '--ignore-config', '--no-playlist', '--no-progress',
        '--no-warnings', '--socket-timeout', '15', '--retries', '0', '--fragment-retries', '0',
        '--max-filesize', str(MAX_BYTES), '--match-filter', 'duration <=? 180', '--use-extractors', 'Instagram',
        '-f', 'b[ext=mp4]', '--write-info-json', '-o', str(target)]
    if cookies:
        command += ['--cookies', str(cookies)]
    response = run(command+['--', url], 65)
    if response.returncode or not target.exists():
        return None, {}
    validate_video(target)
    meta_path = directory/'yt-media.info.json'
    metadata = json.loads(meta_path.read_text(encoding='utf-8')) if meta_path.exists() else {}
    return target, {k: metadata.get(k) for k in ('title', 'description', 'uploader', 'duration', 'thumbnail')}


@contextmanager
def browser():
    from playwright.sync_api import sync_playwright
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(LOCAL/'browsers'))
    PROFILE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(str(PROFILE), headless=False, accept_downloads=False)
        context.set_default_timeout(15000)
        try:
            yield context
        finally:
            context.close()


def verify_session(context):
    page = context.new_page()
    try:
        page.goto('https://www.instagram.com/', wait_until='domcontentloaded', timeout=30000)
        page.wait_for_timeout(1500)
        session = any(c['name'] == 'sessionid' and c['value'] for c in context.cookies(['https://www.instagram.com/']))
        # Public DOM only: own profile exposes the edit-profile link to its owner.
        if not session:
            return False
        page.goto('https://www.instagram.com/'+ACCOUNT+'/', wait_until='domcontentloaded', timeout=30000)
        page.locator('a[href^="/accounts/edit"],a[href="https://www.instagram.com/accounts/edit/"]').first.wait_for(state='visible', timeout=15000)
        return urlsplit(page.url).path.rstrip('/') == '/'+ACCOUNT
    except Exception:
        return False
    finally:
        page.close()


def playwright_fetch(context, url, directory):
    page = context.new_page()
    candidates = []
    def whole_media_url(value):
        u = urlsplit(value)
        return urlunsplit((u.scheme, u.netloc, u.path, urlencode([(k,v) for k,v in parse_qsl(u.query, keep_blank_values=True) if k not in {'bytestart','byteend'}]), ''))
    def capture(response):
        try:
            current_page = urlsplit(page.url)
            canonical_page = urlunsplit((current_page.scheme,current_page.netloc,current_page.path.replace('/reels/','/reel/',1),'',''))
            if response.request.frame != page.main_frame or reel_url(canonical_page) != url:
                return
            mime = response.headers.get('content-type', '').split(';')[0]
            if mime.startswith('video/'):
                # Reels view preloads other posts. Accept only the displayed video's
                # own direct source; blob/DASH sources use the permalink extractor.
                source = page.evaluate('''() => {
                    const videos=[...document.querySelectorAll('video')];
                    const visible=videos.map(v=>{const r=v.getBoundingClientRect();return {v,area:Math.max(0,Math.min(r.right,innerWidth)-Math.max(r.left,0))*Math.max(0,Math.min(r.bottom,innerHeight)-Math.max(r.top,0))};}).sort((a,b)=>b.area-a.area);
                    return visible[0]?.area>0 ? visible[0].v.currentSrc : '';
                }''')
                if not isinstance(source,str) or not source.startswith('https://') or whole_media_url(source) != whole_media_url(response.url):
                    return
                media_url(response.url)
                candidate = whole_media_url(response.url)
                if candidate not in candidates:
                    candidates.append(candidate)
        except Exception:
            pass
    page.on('response', capture)
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=30000)
        page.locator('video').first.wait_for(timeout=15000)
        page.locator('video').first.evaluate('(v) => {v.muted=true; v.play().catch(()=>{});} ')
        page.wait_for_timeout(4000)
        # Caption/creator evidence from the opened post only.
        caption = page.locator('meta[property="og:description"]').get_attribute('content') or '' if page.locator('meta[property="og:description"]').count() else ''
        caption = caption[:12000]
        for candidate in candidates[:4]:
            try:
                return download(candidate, directory/'reel.mp4'), caption
            except (ValueError, OSError, requests.RequestException, subprocess.SubprocessError):
                continue
        return None, caption
    finally:
        page.close()


def instaloader_fetch(context, url, directory):
    import instaloader
    loader = instaloader.Instaloader(max_connection_attempts=1, request_timeout=15, quiet=True)
    cookies = {c['name']: c['value'] for c in context.cookies(['https://www.instagram.com/']) if c['domain'].lstrip('.') == 'instagram.com'}
    loader.context.load_session(ACCOUNT, cookies)
    post = instaloader.Post.from_shortcode(loader.context, urlsplit(url).path.split('/')[2])
    if not post.is_video:
        return None, ''
    return download(post.video_url, directory/'instaloader.mp4'), (post.caption or '')[:12000]


def gallery_fetch(url, directory, cookies):
    # Resolve only; media download goes through the same origin/size/duration validator.
    result = run([sys.executable, '-m', 'gallery_dl', '--ignore-config', '--cookies', str(cookies), '-g', url], 45)
    if result.returncode:
        return None
    for candidate in result.stdout.decode(errors='replace').splitlines()[:10]:
        try:
            return download(candidate, directory/'gallery.mp4')
        except (ValueError, OSError, requests.RequestException, subprocess.SubprocessError):
            continue
    return None


def analyze(path, directory):
    meta = validate_video(path)
    frames = directory/'frame-%02d.jpg'
    run([ffmpeg(), '-v', 'error', '-y', '-protocol_whitelist', 'file,pipe', '-i', str(path), '-vf', f'fps={8/meta["duration"]},scale=960:-2', '-frames:v', '8', str(frames)], 40)
    images = list(directory.glob('frame-*.jpg'))[:8]
    texts = []
    try:
        import pytesseract
        from PIL import Image
        for image in images:
            with Image.open(image) as im:
                texts.append(pytesseract.image_to_string(im, timeout=10))
    except Exception:
        pass
    if not any(t.strip() for t in texts):
        try:
            from rapidocr_onnxruntime import RapidOCR
            engine = RapidOCR()
            for image in images:
                result, _ = engine(str(image))
                texts.append(' '.join(line[1] for line in (result or [])))
        except Exception:
            pass
    transcript = ''
    audio = directory/'audio.wav'
    if meta['audio']:
        result = run([ffmpeg(), '-v', 'error', '-y', '-protocol_whitelist', 'file,pipe', '-i', str(path), '-t', '180', '-vn', '-ac', '1', '-ar', '16000', str(audio)], 30)
        if result.returncode == 0:
            try:
                from faster_whisper import WhisperModel
                import wave
                import numpy as np
                model = WhisperModel('base', device='cpu', compute_type='int8', download_root=str(LOCAL/'models'))
                # PCM avoids depending on PyAV's changing container keyword arguments.
                with wave.open(str(audio), 'rb') as source:
                    samples = np.frombuffer(source.readframes(source.getnframes()), dtype=np.int16).astype(np.float32)/32768.0
                segments, _ = model.transcribe(samples, beam_size=1)
                transcript = ' '.join(s.text for s in segments)[:24000]
            except Exception:
                pass
    text = '\n'.join(texts)[:16000]
    evidence = transcript+' '+text
    links = re.findall(r'https://[A-Za-z0-9./_?=&%-]+', evidence)
    # Accept exact visible URLs without scheme; never repair guessed OCR domains.
    repos = list(dict.fromkeys('https://github.com/'+m for m in re.findall(r'\bgithub\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)', evidence, re.I)))[:10]
    named = re.findall(r'\b(?:se llama|llamado|called|named|nombre es)\s+["\u201c\u201d\']?([A-Za-z][A-Za-z0-9_.+-]{1,60})', transcript, re.I)
    names = list(dict.fromkeys(n.casefold() for n in named))[:3]
    return {'transcript': transcript, 'visual_findings': text, 'links': links[:20],
        'repositories': repos, 'project_names': names,
        'coverage': 'FULL_VIDEO_BYTES_PROVIDED', 'frame_extraction': [{'frames': len(images), 'audio': 'EXTRACTED' if audio.exists() else 'NO_AUDIO', 'duration': meta['duration']}]}


def fetch(job, directory, progress):
    if job.get('kind') != 'FETCH_INSTAGRAM_REEL' or set(job)-{'kind','url','inbox_item_id','lease','timeout'}:
        raise ValueError('JOB_FORBIDDEN')
    url = reel_url(job['url'])
    caption = ''; path = None; extractor = None; attempts = []
    progress('FETCHING_VIDEO')
    try:
        path, meta = ytdlp(url, directory)
        if path:
            caption = str(meta.get('description') or meta.get('title') or '')
            extractor = 'yt-dlp-public'
    except Exception:
        pass
    attempts.append({'extractor': 'yt-dlp-public', 'success': bool(path)})
    if not path:
        progress('OPENING_INSTAGRAM')
        with browser() as context:
            if not verify_session(context):
                return {'status': 'LOGIN_REQUIRED', 'attempts': attempts}, None
            progress('FETCHING_VIDEO')
            try:
                path, caption = playwright_fetch(context, url, directory)
                if path: extractor = 'playwright'
            except Exception:
                pass
            attempts.append({'extractor': 'playwright', 'success': bool(path)})
            jar = cookie_jar(context, directory)
            if not path:
                try:
                    path, _ = ytdlp(url, directory, jar)
                    if path: extractor = 'yt-dlp'
                except Exception:
                    pass
                attempts.append({'extractor': 'yt-dlp', 'success': bool(path)})
            if not path:
                try:
                    path, extra = instaloader_fetch(context, url, directory)
                    caption = caption or extra
                    if path: extractor = 'instaloader'
                except Exception:
                    pass
                attempts.append({'extractor': 'instaloader', 'success': bool(path)})
            if not path:
                try:
                    path = gallery_fetch(url, directory, jar)
                    if path: extractor = 'gallery-dl'
                except Exception:
                    pass
                attempts.append({'extractor': 'gallery-dl', 'success': bool(path)})
    if not path:
        return {'status': 'METADATA_ONLY' if caption else 'EXTRACTOR_FAILED', 'caption': caption, 'attempts': attempts}, None
    progress('VIDEO_DOWNLOADED'); progress('TRANSCRIBING')
    analysis = analyze(path, directory)
    progress('ANALYZING')
    return {'status': 'FULL_MEDIA', 'extractor': extractor, 'caption': caption, 'analysis': analysis, 'attempts': attempts}, path


def transport(config):
    base = config.get('cloud', '').rstrip('/')
    u = urlsplit(base)
    if base != 'https://web-production-a9565.up.railway.app' or u.username or not 32 <= len(config.get('token', '')) <= 256:
        raise ValueError('INVALID_WORKER_CONFIG')
    client = requests.Session(); client.trust_env = False
    client.auth = BearerAuth(config['token'])
    return client, base+'/api/reposnews/local-worker'


def _fetch_child(job, directory, events):
    try:
        manifest, video = fetch(job, Path(directory), lambda stage: events.put(('progress', stage)))
        events.put(('result', (manifest, str(video) if video else None)))
    except Exception:
        events.put(('error', 'EXTRACTOR_FAILED'))


def fetch_bounded(job, directory, progress):
    """Kill a stuck browser/extractor/transcriber after five minutes."""
    context = multiprocessing.get_context('spawn')
    events = context.Queue()
    process = context.Process(target=_fetch_child, args=(job, str(directory), events))
    process.start(); deadline = time.monotonic()+300
    try:
        while time.monotonic() < deadline:
            try:
                kind, value = events.get(timeout=1)
            except queue.Empty:
                if not process.is_alive():
                    break
                continue
            if kind == 'progress':
                progress(value)
            elif kind == 'result':
                manifest, filename = value
                video = Path(filename).resolve() if filename else None
                if video and not video.is_relative_to(directory.resolve()):
                    raise ValueError('INVALID_OUTPUT_PATH')
                return manifest, video
            else:
                break
        return {'status':'EXTRACTOR_FAILED'}, None
    finally:
        process.join(timeout=1)
        if process.is_alive():
            if os.name == 'nt':
                # Only the process tree created for this job, never another browser.
                run(['taskkill', '/PID', str(process.pid), '/T', '/F'], 10)
            else:
                process.terminate()
        process.join(timeout=5); events.close()


@contextmanager
def single_worker():
    LOCAL.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (LOCAL/'worker.lock').open('a+b') as handle:
        handle.seek(0,2)
        if not handle.tell():
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def _main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--login', action='store_true')
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--config', type=Path, default=LOCAL/'config.json')
    args = parser.parse_args()
    if os.environ.get('RAILWAY_ENVIRONMENT') or os.environ.get('RAILWAY_PROJECT_ID'):
        raise ValueError('LOCAL_PC_ONLY')
    LOCAL.mkdir(parents=True, exist_ok=True, mode=0o700)
    if args.login:
        with browser() as context:
            page = context.new_page(); page.goto('https://www.instagram.com/')
            print('Inicia sesión como @zaragente031 en Instagram. No introduzcas credenciales en ZAR.', flush=True)
            while context.pages:
                try:
                    if verify_session(context):
                        (LOCAL/'session-status.json').write_text(json.dumps({'session':'CONNECTED','account':ACCOUNT,'verified_at':time.time()}),encoding='utf-8')
                        print('CONNECTED · @zaragente031. Perfil persistido localmente.',flush=True)
                        return
                    page.wait_for_timeout(5000)
                except Exception:
                    break
        return
    config = json.loads(args.config.read_text(encoding='utf-8'))
    client, base = transport(config)
    session_state = 'EXPIRED'
    with browser() as context:
        if verify_session(context):
            session_state = 'CONNECTED'
    def heartbeat_loop():
        heart, endpoint = transport(config)
        while True:
            time.sleep(20)
            try:
                heart.post(endpoint+'/heartbeat',json={'session':session_state},timeout=(5,10),allow_redirects=False)
            except requests.RequestException:
                pass
    threading.Thread(target=heartbeat_loop, name='instagram-heartbeat', daemon=True).start()
    while True:
        try:
            response = client.post(base+'/poll', json={'session': session_state}, timeout=(5, 20), allow_redirects=False)
            response.raise_for_status(); job = response.json().get('job')
            if job:
                if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', job.get('inbox_item_id', '')):
                    raise ValueError('INVALID_ITEM_ID')
                endpoint = base+'/jobs/'+job['inbox_item_id']
                headers = {'X-ZAR-Job-Lease': job['lease']}
                def progress(stage):
                    r = client.post(endpoint+'/progress', json={'stage':stage}, headers=headers, timeout=(5,15), allow_redirects=False)
                    r.raise_for_status()
                with tempfile.TemporaryDirectory(prefix='job-', dir=LOCAL) as tmp:
                    manifest, video = fetch_bounded(job, Path(tmp), progress)
                    session_state = 'EXPIRED' if manifest['status']=='LOGIN_REQUIRED' else 'CONNECTED' if manifest.get('extractor') != 'yt-dlp-public' else session_state
                    if video:
                        with video.open('rb') as f:
                            r = client.post(endpoint+'/result', data={'manifest':json.dumps(manifest)}, files={'video':('reel.mp4',f,'video/mp4')}, headers=headers, timeout=(10,240), allow_redirects=False)
                    else:
                        r = client.post(endpoint+'/result', data={'manifest':json.dumps(manifest)}, headers=headers, timeout=(5,30), allow_redirects=False)
                    r.raise_for_status()
                    # Local report contains no cookie, CDN URL, caption or credential.
                    report = {'item':job['inbox_item_id'],'source':reel_url(job['url']),'status':manifest['status'], 'extractor':manifest.get('extractor'),'attempts':manifest.get('attempts'),
                        'transcript':bool(manifest.get('analysis',{}).get('transcript')),'frames':manifest.get('analysis',{}).get('frame_extraction',[])}
                    (LOCAL/'last-job.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        except (OSError, ValueError, requests.RequestException, subprocess.SubprocessError):
            print('Worker: conexión/trabajo pendiente; consulta ReposNews Inbox.', flush=True)
        if args.once:
            return
        time.sleep(10)


def main():
    with single_worker():
        _main()


if __name__ == '__main__':
    main()
