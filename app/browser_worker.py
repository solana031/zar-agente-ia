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


def run():
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=True, chromium_sandbox=True,
        executable_path=os.environ.get('ZAR_BROWSER_EXECUTABLE') or None,
        proxy={'server': os.environ['ZAR_BROWSER_PROXY'], 'bypass': '<-loopback>'},
        args=['--disable-dev-shm-usage', '--disable-quic', '--force-webrtc-ip-handling-policy=disable_non_proxied_udp'])
    first = json.loads(sys.stdin.readline())
    context = browser.new_context(storage_state=first.get('storage') or None,
        viewport={'width': 1280, 'height': 800}, accept_downloads=True, service_workers='block')
    context.set_default_timeout(10000)
    # Reject alternative protocols and unsafe HTTP methods from page scripts.
    def route(request_route):
        request = request_route.request
        if not request.url.startswith('https://') or request.method not in ('GET', 'HEAD', 'OPTIONS') and not permit[0]:
            request_route.abort()
        else:
            request_route.continue_()
    permit = [False]
    context.route('**/*', route)
    page = context.new_page()
    controls = []
    downloads = []
    def download(item):
        downloads.append(item)
    context.on('page', lambda new: new.on('download', download))
    page.on('download', download)
    for line in sys.stdin:
        try:
            data = json.loads(line)
            action = data.get('action', 'read')
            if action == 'close':
                break
            if action == 'open':
                page.goto(data['url'], wait_until='domcontentloaded', timeout=30000)
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
            elif action in ('click', 'fill', 'upload'):
                index = int(data['index'])
                control = controls[index]
                decision = policy(control['label'] + ' ' + control.get('type', ''), action)
                if decision in ('HUMAN_ACTION', 'DENY') or decision == 'CONFIRM' and data.get('confirmed') is not True:
                    print(json.dumps({'ok': False, 'status': 'ACTION_REQUIRED', 'reason': 'Intervención humana: ' + decision, 'decision': decision}), flush=True)
                    continue
                locator = page.locator('[data-zar-control="%s"]' % index)
                if locator.count() != 1:
                    raise ValueError('Control cambiado; vuelve a leer la página')
                current = locator.evaluate("e=>({type:e.getAttribute('type')||'',label:(e.getAttribute('aria-label')||e.innerText||e.getAttribute('placeholder')||e.name||e.tagName).slice(0,180),form:e.form?.innerText||''})")
                if current['label'] != control['label'] or current['type'] != control['type']:
                    raise ValueError('Control cambiado; vuelve a leer la página')
                if action != 'fill' and policy(current['label'] + ' ' + current['form'], action) in ('HUMAN_ACTION', 'DENY'):
                    print(json.dumps({'ok':False,'status':'ACTION_REQUIRED','reason':'Formulario legal/financiero: intervención humana requerida.'}),flush=True)
                    continue
                if action == 'fill':
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
                    permit[0] = bool(data.get('confirmed'))
                    try:
                        locator.click()
                        page.wait_for_timeout(350)
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
            controls = page.evaluate('''() => [...document.querySelectorAll('a[href],button,input:not([type=hidden]),textarea,select')].filter(e=>e.getBoundingClientRect().width&&e.getBoundingClientRect().height).slice(0,150).map((e,i)=>{e.setAttribute('data-zar-control',i);return {index:i,tag:e.tagName,type:e.getAttribute('type')||'',label:(e.getAttribute('aria-label')||e.innerText||e.getAttribute('placeholder')||e.name||e.tagName).slice(0,180)}})''')
            visible = page.locator('body').inner_text()[:18000]
            sensitive = bool(re.search(r'api\s*(?:key|secret)|access\s*token|refresh\s*token|private\s*key', visible, re.I))
            if sensitive:
                visible = 'Vista con credenciales: contenido y captura ocultos. Revisión personal requerida.'
                controls = []
            else:
                visible = re.sub(r'\b(?:eyJ[A-Za-z0-9_.-]{30,}|sk-[A-Za-z0-9_-]{15,}|AIza[A-Za-z0-9_-]{20,})\b', '[REDACTED]', visible)
            challenge = human_gate(page.title(), visible)
            url = urlsplit(page.url)
            print(json.dumps({'ok': True, 'status': 'ACTION_REQUIRED' if challenge else 'READY',
                'reason': security_state(page.title(),visible)+' · intervención personal requerida' if challenge else '',
                'security_state':security_state(page.title(),visible),
                'url': url.scheme + '://' + url.netloc + url.path, 'title': page.title(),
                'text': visible, 'controls': controls,
                'pages': [{'index': i, 'title': x.title()} for i, x in enumerate(context.pages)],
                'downloads': [{'index': i, 'name': x.suggested_filename} for i, x in enumerate(downloads)],
                'screenshot': '' if sensitive else base64.b64encode(page.screenshot(type='jpeg', quality=60, mask=[page.locator('input,textarea')])).decode(),
                'storage': context.storage_state()}), flush=True)
        except Exception:
            # Provider/browser errors can embed credential-bearing URLs. Never echo them.
            print(json.dumps({'ok': False, 'status': 'ERROR', 'reason': 'La navegación no terminó. Comprueba URL, red y control; no se reintenta automáticamente.'}), flush=True)
    context.close()
    browser.close()
    p.stop()


if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        print(json.dumps({'ok': False, 'status': 'ACTION_REQUIRED', 'reason': 'Chromium sandbox no disponible; revisar runtime del navegador (' + type(exc).__name__ + ').'}), flush=True)
