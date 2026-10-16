"""Unprivileged Chromium actor. JSON pipe only; never logs page/credential data."""
import base64
import json
import os
import re
import sys
from urllib.parse import urlsplit


def policy(label, action):
    text = str(label).casefold()
    if re.search(r'\b(trading|trade|buy|sell)\b|invertir|operar en vivo', text):
        return 'DENY'
    if action == 'fill':
        return 'HUMAN_ACTION' if re.search(r'password|contrase|otp|verification|verificaci|captcha|passkey|bank|banc|tax|fiscal|birth|nacimiento|tel[eé]fono|phone|card|tarjeta', text) else 'ALLOW'
    if re.search(r'accept|acept|agree|t[eé]rmin|terms|consent|pagar|pay|subscribe|suscri|purchase|comprar|delete|borrar|captcha', text):
        return 'HUMAN_ACTION'
    # Generic buttons can submit external changes. They require explicit review.
    return 'CONFIRM'


def human_gate(title, text):
    return security_state(title,text)!='READY'

def security_state(title,text):
    if re.search(r'captcha|verify you are human|checking your browser|security verification',text,re.I) or re.fullmatch(r'just a moment\.{0,3}|security check',title.strip(),re.I):return 'CAPTCHA'
    if re.search(r'2-step verification|two.factor authentication|verificaci[oó]n en dos pasos|passkey',text,re.I):return '2FA'
    if re.fullmatch(r'access denied|forbidden|acceso denegado',title.strip(),re.I):return 'BLOCKED'
    if re.fullmatch(r'payment required|pago requerido|checkout',title.strip(),re.I):return 'PAYMENT_REQUIRED'
    if re.fullmatch(r'log.?in|sign.?in|iniciar sesi[oó]n',title.strip(),re.I):return 'LOGIN_REQUIRED'
    return 'READY'


def instagram_host(url):
    host = urlsplit(url).hostname or ''
    return host in ('instagram.com', 'www.instagram.com') or host.endswith(('.cdninstagram.com', '.fbcdn.net'))


def instagram_login_post(url, body=''):
    if isinstance(body,bytes): body=body.decode('utf-8','replace')
    if not isinstance(body,str): return False
    parsed = urlsplit(url)
    if parsed.hostname not in ('instagram.com', 'www.instagram.com'): return False
    if parsed.path.rstrip('/') in ('/api/graphql', '/graphql/query'):
        from urllib.parse import parse_qs
        try:
            payload=json.loads(body) if body.lstrip().startswith('{') else {k:v[0] for k,v in parse_qs(body).items()}
            operation=str(payload.get('fb_api_req_friendly_name') or payload.get('operationName') or '')
        except (ValueError,TypeError,AttributeError): return False
        return bool(re.fullmatch(r'(?:use)?Polaris(?:Login|AccountsLogin|LoginAccount)[A-Za-z]{0,50}Mutation',operation))
    if re.fullmatch(r'/api/v1/bloks/apps/com\.bloks\.www\.(?:bloks\.)?caa\.login\.async\.send_login_request/?',parsed.path): return True
    return bool(re.search(r'^/(accounts/login|accounts/onetap|challenge|api/v1/(web/accounts/login|accounts/(login|two_factor_login)|challenge))(/|$)', parsed.path))


def instagram_control(page, spec):
    """Resolve current login controls by identity, never a stale array offset."""
    if not isinstance(spec, dict): raise ValueError('LOGIN_CONTROL_REQUIRED')
    name = spec.get('name', '')
    if spec.get('tag') == 'INPUT' and name in ('email','username','pass','password','verificationCode','security_code','verification_code','otp'):
        return page.locator('input[name="'+name+'"]')
    label = spec.get('label', '')
    if isinstance(label,str) and re.fullmatch(r'log in|iniciar sesi[oó]n|entrar|confirm|confirmar|verify|verificar',label.strip(),re.I):
        return page.get_by_role('button',name=label,exact=True)
    raise ValueError('LOGIN_CONTROL_NOT_ALLOWED')


def request_body(request):
    """Network payload metadata is optional; decoding errors must fail closed."""
    try:
        body=request.post_data
        return body if isinstance(body,(str,bytes)) else ''
    except (TypeError,ValueError,UnicodeError):
        return ''


def run():
    from playwright.sync_api import sync_playwright
    from browser_diagnostics import event as network_event
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=True, chromium_sandbox=True,
        executable_path=os.environ.get('ZAR_BROWSER_EXECUTABLE') or None,
        proxy={'server': os.environ['ZAR_BROWSER_PROXY'], 'bypass': '<-loopback>'},
        args=['--disable-dev-shm-usage', '--disable-quic', '--force-webrtc-ip-handling-policy=disable_non_proxied_udp'])
    first = json.loads(sys.stdin.readline())
    instagram_profile = first.get('instagram_profile') is True
    context = browser.new_context(storage_state=first.get('storage') or None,
        viewport={'width': 1280, 'height': 800}, accept_downloads=True, service_workers='block')
    context.set_default_timeout(10000)
    # Reject alternative protocols and unsafe HTTP methods from page scripts.
    callback_errors=[]
    network_events=[]
    request_events={}
    def route(request_route):
        nonlocal request_events
        try:
            request = request_route.request
            denied=not request.url.startswith('https://') or instagram_profile and not instagram_host(request.url) or request.method not in ('GET', 'HEAD', 'OPTIONS') and not (permit[0] and (not instagram_profile or instagram_login_post(request.url, request_body(request))))
            if instagram_profile:
                rule='BLOCK_NON_HTTPS' if not request.url.startswith('https://') else 'BLOCK_PROFILE_HOST' if not instagram_host(request.url) else 'BLOCK_METHOD_OR_OPERATION' if denied else 'ALLOW_PROFILE_REQUEST'
                entry=network_event(request.url,request.method,request.resource_type,rule)
                request_events[request]=entry;network_events.append(entry)
                if len(network_events)>60:
                    network_events.pop(0)
                    request_events={k:v for k,v in request_events.items() if any(v is e for e in network_events)}
            if denied:
                if instagram_profile and request.method == 'POST' and len(blocked_posts)<6:
                    blocked_posts.append(network_event(request.url,request.method,request.resource_type,'BLOCK_METHOD_OR_OPERATION')['classification'])
                request_route.abort()
            else:
                request_route.continue_()
        except Exception as exc:
            callback_errors.append({'callback':'REQUEST_ROUTE','exception_type':type(exc).__name__})
            del callback_errors[:-6]
            try:request_route.abort()
            except Exception:pass
    permit = [False]
    blocked_posts = []
    context.route('**/*', route)
    page = context.new_page()
    controls = []
    downloads = []
    def download(item):
        downloads.append(item)
    context.on('page', lambda new: new.on('download', download))
    page.on('download', download)
    login_http = [None]
    blocked_posts = []
    public_media = []
    def observed_media(response):
        try:
            if instagram_profile and response.request in request_events:
                entry=request_events[response.request];entry['http_status']=response.status
                if response.request.redirected_from:
                    entry['classification']='REDIRECT';entry['redirect_hostname']=urlsplit(response.url).hostname or ''
            if instagram_profile and response.request.method=='POST' and instagram_login_post(response.url,request_body(response.request)): login_http[0] = response.status
            mime = response.headers.get('content-type', '').split(';')[0]
            if response.request.method == 'GET' and response.url.startswith('https://') and mime.startswith(('video/', 'audio/')) and len(public_media) < 10:
                public_media.append({'type': mime.split('/')[0], 'url': response.url})
        except Exception as exc:
            callback_errors.append({'callback':'RESPONSE_METADATA','exception_type':type(exc).__name__})
            del callback_errors[:-6]
    page.on('response', observed_media)
    for line in sys.stdin:
        try:
            data = json.loads(line)
            action = data.get('action', 'read')
            step = 'CONTROL_VALIDATION' if action in ('fill','click') else 'NAVIGATION'
            human_login = instagram_profile and data.get('human_login') is True
            if action == 'close':
                break
            if action == 'instagram_login':
                if not instagram_profile:raise ValueError('Dedicated profile required')
                step='LOGIN_FIELDS'
                page.locator('input[name="email"],input[name="username"]').fill('zaragente031@gmail.com')
                page.locator('input[name="pass"],input[name="password"]').fill(str(data.pop('password','')))
                permit[0]=True
                try:
                    step='LOGIN_DISPATCH'
                    page.get_by_role('button',name=re.compile(r'^log in$',re.I)).click()
                    step='LOGIN_WAIT'
                    page.wait_for_timeout(3000)
                finally:permit[0]=False
            elif action == 'open':
                if instagram_profile and not instagram_host(data['url']): raise ValueError('Instagram profile only')
                public_media.clear()
                page.goto(data['url'], wait_until='domcontentloaded', timeout=30000)
                if instagram_profile: page.wait_for_timeout(2500)
                elif data.get('discovery'): page.wait_for_timeout(1200)
            elif action == 'new_page':
                if len(context.pages)>=8:raise ValueError('Maximum browser pages reached')
                page=context.new_page()
                page.goto(data['url'],wait_until='domcontentloaded',timeout=30000)
            elif action == 'close_page':
                if len(context.pages)<=1:raise ValueError('Keep at least one browser page')
                target=context.pages[int(data['index'])]
                target.close()
                if page==target:page=context.pages[-1]
            elif action in ('back', 'forward', 'reload'):
                getattr(page, {'back': 'go_back', 'forward': 'go_forward', 'reload': 'reload'}[action])(wait_until='domcontentloaded', timeout=30000)
            elif action == 'page':
                page = context.pages[int(data['index'])]
            elif action == 'instagram_verify':
                if not instagram_profile: raise ValueError('Dedicated profile required')
                page.goto('https://www.instagram.com/zaragente031/', wait_until='domcontentloaded', timeout=30000)
                page.wait_for_timeout(1200)
                own = page.locator('a[href="/accounts/edit/"],a[href="https://www.instagram.com/accounts/edit/"]').count() > 0
                identity = own and bool(re.search(r'\bzaragente031\b', page.locator('body').inner_text()))
                print(json.dumps({'ok': True, 'status': 'VERIFIED' if identity else 'ACTION_REQUIRED', 'account': 'zaragente031' if identity else '', 'authenticated': identity,
                    'storage': context.storage_state()}), flush=True)
                continue
            elif action in ('click', 'fill', 'upload'):
                if human_login:
                    locator=instagram_control(page,data.get('control'))
                    if locator.count()!=1:raise ValueError('LOGIN_CONTROL_CHANGED_REFRESH_REQUIRED')
                    control=locator.evaluate("e=>({tag:e.tagName,type:e.getAttribute('type')||'',label:(e.getAttribute('aria-label')||e.innerText||e.getAttribute('placeholder')||e.name||e.tagName).slice(0,180)})")
                else:
                    index = int(data['index'])
                    if not 0<=index<len(controls):raise ValueError('CONTROL_CHANGED_REFRESH_REQUIRED')
                    control = controls[index]
                    locator = page.locator('[data-zar-control="%s"]' % index)
                decision = policy(control['label'] + ' ' + control.get('type', ''), action)
                if human_login and action == 'fill' and control.get('tag') == 'INPUT' and not re.search(r'captcha|bank|banc|tax|fiscal|card|tarjeta|phone|tel[eé]fono', control['label'], re.I): decision = 'ALLOW'
                if human_login and action == 'click' and re.fullmatch(r'log in|iniciar sesi[oó]n|entrar|confirm|confirmar|verify|verificar', control['label'].strip(), re.I): decision = 'ALLOW'
                if decision in ('HUMAN_ACTION', 'DENY') or decision == 'CONFIRM' and data.get('confirmed') is not True:
                    print(json.dumps({'ok': False, 'status': 'ACTION_REQUIRED', 'reason': 'Intervención humana: ' + decision, 'decision': decision}), flush=True)
                    continue
                if locator.count() != 1:
                    raise ValueError('Control cambiado; vuelve a leer la página')
                current = locator.evaluate("e=>({type:e.getAttribute('type')||'',label:(e.getAttribute('aria-label')||e.innerText||e.getAttribute('placeholder')||e.name||e.tagName).slice(0,180),form:e.form?.innerText||''})")
                if current['label'] != control['label'] or current['type'] != control['type']:
                    raise ValueError('Control cambiado; vuelve a leer la página')
                if action != 'fill' and not human_login and policy(current['label'] + ' ' + current['form'], action) in ('HUMAN_ACTION', 'DENY'):
                    print(json.dumps({'ok':False,'status':'ACTION_REQUIRED','reason':'Formulario legal/financiero: intervención humana requerida.'}),flush=True)
                    continue
                if action == 'fill':
                    step = 'FILL'
                    locator.fill(str(data.get('value', ''))[:5000])
                elif action == 'upload':
                    if control.get('type') != 'file':
                        raise ValueError('Control no es una subida')
                    permit[0] = True
                    try:
                        locator.set_input_files(data['path'])
                        page.wait_for_timeout(350)
                    finally:
                        permit[0] = False
                else:
                    permit[0] = bool(data.get('confirmed')) or human_login
                    try:
                        step = 'CLICK'
                        login_http[0] = None
                        blocked_posts.clear()
                        step = 'CLICK_DISPATCH'
                        locator.click()
                        step = 'LOGIN_RESPONSE_WAIT'
                        page.wait_for_timeout(3000 if human_login else 350)
                    finally:
                        permit[0] = False
            elif action == 'download':
                item = downloads[int(data['index'])]
                path = item.path()
                if not path or os.path.getsize(path) > 15 * 1024 * 1024:
                    raise ValueError('Descarga superior a 15 MB o incompleta')
                with open(path, 'rb') as handle:
                    content = base64.b64encode(handle.read()).decode()
                print(json.dumps({'ok': True, 'file': content, 'name': item.suggested_filename}), flush=True)
                continue
            elif action != 'read':
                raise ValueError('Acción no disponible')
            # Values/passwords are deliberately excluded from the visible control list.
            step='READ_CONTROLS'
            if instagram_profile:
                controls=[]
                for selector,tag in [('input:not([type=hidden])','INPUT'),('button,[role=button]','BUTTON')]:
                    for element in page.locator(selector).all()[:100]:
                        if not element.is_visible():continue
                        name=element.get_attribute('name') or ''
                        label=element.get_attribute('aria-label') or element.inner_text() or element.get_attribute('placeholder') or name or tag
                        controls.append({'index':len(controls),'tag':tag,'name':name,'type':element.get_attribute('type') or '', 'role':element.get_attribute('role') or '', 'label':label[:180]})
            else:
                controls = page.evaluate('''profile => [...document.querySelectorAll('a[href],button,input:not([type=hidden]),textarea,select'+(profile?', [role=button]':''))].filter(e=>e.getBoundingClientRect().width&&e.getBoundingClientRect().height).slice(0,150).map((e,i)=>{e.setAttribute('data-zar-control',i);return {index:i,tag:e.tagName,name:e.name||'',role:e.getAttribute('role')||'',type:e.getAttribute('type')||'',label:(e.getAttribute('aria-label')||e.innerText||e.getAttribute('placeholder')||e.name||e.tagName).slice(0,180)}})''', arg=instagram_profile)
            visible = page.locator('body').inner_text()[:18000]
            sensitive = bool(re.search(r'api\s*(?:key|secret)|access\s*token|refresh\s*token|private\s*key', visible, re.I))
            if sensitive:
                visible = 'Vista con credenciales: contenido y captura ocultos. Revisión personal requerida.'
                controls = []
            else:
                visible = re.sub(r'\b(?:eyJ[A-Za-z0-9_.-]{30,}|sk-[A-Za-z0-9_-]{15,}|AIza[A-Za-z0-9_-]{20,})\b', '[REDACTED]', visible)
            challenge = human_gate(page.title(), visible)
            url = urlsplit(page.url)
            discovery = {}
            if data.get('discovery') and not challenge and not sensitive:
                if not re.search(r'log in to see|inicia sesi[oó]n para|sign in to continue', visible, re.I):
                    page.evaluate('''() => {const v=document.querySelector('main video,article video');if(v){v.muted=true;v.play().catch(()=>{});}}''')
                    page.wait_for_timeout(1000)
                discovery = page.evaluate('''() => ({
                  metadata:Object.fromEntries([...document.querySelectorAll('meta[property],meta[name]')].filter(e=>/^(og:(title|description|image|video|video:url)|description|author)$/.test(e.getAttribute('property')||e.getAttribute('name'))).map(e=>[e.getAttribute('property')||e.getAttribute('name'),(e.content||'').slice(0,6000)])),
                  media:[...document.querySelectorAll('main video,main audio,article video,article audio,main video source,article video source')].slice(0,10).map(e=>({type:e.tagName==='AUDIO'?'audio':'video',url:e.currentSrc||e.src||''})).filter(e=>e.url.startsWith('https://')),
                  links:[...document.querySelectorAll('main a[href],article a[href]')].slice(0,20).map(e=>e.href).filter(u=>u.startsWith('https://')),
                  caption:(document.querySelector('main,article')?.innerText||'').slice(0,12000)
                })''')
                if not discovery['media'] and len(public_media)==1: discovery['media'] += public_media
            print(json.dumps({'ok': True, 'status': 'ACTION_REQUIRED' if challenge else 'READY',
                'reason': security_state(page.title(),visible)+' · intervención personal requerida' if challenge else '',
                'security_state':security_state(page.title(),visible),
                'url': url.scheme + '://' + url.netloc + url.path, 'title': page.title(),
                'text': visible, 'controls': controls, 'discovery': discovery,
                'login_http': login_http[0] if instagram_profile else None, 'blocked_post_classes': blocked_posts[:] if instagram_profile else [], 'network_callbacks':callback_errors[:], 'network_diagnostics':network_events[:] if instagram_profile else [],
                'pages': [{'index': i, 'title': x.title()} for i, x in enumerate(context.pages)],
                'downloads': [{'index': i, 'name': x.suggested_filename} for i, x in enumerate(downloads)],
                'screenshot': '' if sensitive else base64.b64encode(page.screenshot(type='jpeg', quality=60, mask=[page.locator('input,textarea')])).decode(),
                'storage': context.storage_state()}), flush=True)
        except Exception as exc:
            import traceback
            trace=traceback.extract_tb(exc.__traceback__)
            frames=[{'function':f.name,'line':f.lineno,'module':os.path.basename(f.filename)} for f in trace if os.path.basename(f.filename)=='browser_worker.py']
            frames += [{'function':f.name,'line':f.lineno,'module':os.path.basename(f.filename)} for f in trace[-8:] if os.path.basename(f.filename)!='browser_worker.py']
            # Provider/browser errors can embed credential-bearing URLs. Never echo them.
            print(json.dumps({'ok': False, 'status': 'ERROR', 'reason': 'La navegación no terminó. No se ha repetido la acción.', 'failed_step': step, 'exception_type': type(exc).__name__, 'trace_location': frames, 'login_http': login_http[0] if instagram_profile else None}), flush=True)
    context.close()
    browser.close()
    p.stop()


if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        print(json.dumps({'ok': False, 'status': 'ACTION_REQUIRED', 'reason': 'Chromium sandbox no disponible; revisar runtime del navegador (' + type(exc).__name__ + ').'}), flush=True)
