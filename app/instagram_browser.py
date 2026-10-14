"""One isolated operational Instagram profile; no imported browser cookies."""
import json
import re
from flask import jsonify, request, session, Response
from . import file_store, oauth_vault
from .user_scope import get_current_user, user_id_for_email

PROFILE = 'zar-instagram-operational'
ACCOUNT = 'zaragente031'


def allowed_owner():
    from . import cloud_auth
    return cloud_auth.connected() and get_current_user() in {
        user_id_for_email('solana031@gmail.com'), user_id_for_email('zaragente031@gmail.com')}


def browser():
    from .zar_browser import actor
    return actor(PROFILE, instagram_profile=True)


def marker():
    return file_store.DATA_DIR / 'users' / PROFILE / 'instagram_identity.enc'


def verify():
    result = browser().run({'action': 'instagram_verify'})
    verified = result.get('authenticated') is True and result.get('account') == ACCOUNT
    if verified:
        oauth_vault.persist(marker(), json.dumps({'account': ACCOUNT, 'verified': True}), file_store.DATA_DIR)
    else:
        marker().unlink(missing_ok=True)
    result['authenticated'] = verified
    result['account'] = ACCOUNT if verified else ''
    result['status'] = 'VERIFIED' if verified else 'ACTION_REQUIRED'
    return result


def discovery(url):
    from .reposnews_inbox import clean_url, safe_caption
    from .reposnews_discovery import sanitize
    if not re.fullmatch(r'https://(?:www\.)?instagram\.com/(?:reel|p)/[A-Za-z0-9_-]+/?', url or ''):
        return {'status': 'UNSUPPORTED'}
    if not marker().exists(): return {'status': 'LOGIN_REQUIRED'}
    try:
        if not verify().get('authenticated'): return {'status': 'LOGIN_REQUIRED'}
        result = browser().run({'action': 'open', 'url': url, 'discovery': True})
        if not result.get('ok') or result.get('security_state') != 'READY':
            return {'status': result.get('security_state', 'SESSION_UNAVAILABLE')}
        return {'status': 'AUTHENTICATED_DISCOVERY', 'text': safe_caption(result.get('text', '')),
                'source': clean_url(url), 'browser_evidence': result.get('discovery', {}), 'account': ACCOUNT}
    except Exception:
        return {'status': 'SESSION_UNAVAILABLE'}  # Never return provider URLs/cookies.


def register(blueprint):
    @blueprint.get('/instagram-browser')
    def login_page():
        if not allowed_owner(): return Response('Acceso reservado al titular conectado de ZAR.', status=403)
        return Response('''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Instagram ZAR · sesión aislada</title><link rel="stylesheet" href="/static/zar-browser.css?v=33.3.64"><body class="zarBrowser igBrowser" style="background:#17130f;color:#ead9c3;font-family:system-ui;padding:20px;max-width:1000px;margin:auto">
<h1>Instagram ZAR · @zaragente031</h1><p>Inicia sesión personalmente en este navegador de servidor. Perfil exclusivo; sesión cifrada. No uses tu cuenta personal. La contraseña y los códigos solo se transmiten al acceso oficial; no se guardan.</p>
<button id="open">Abrir acceso Instagram</button> <button id="read">Actualizar pantalla</button> <button id="verify">Verificar cuenta y continuar Reel conservado</button>
<p id="status" class="zbStatus" role="status"></p><img id="preview" alt="Pantalla del navegador aislado" style="width:100%"><section class="igControlPanel"><h2>Acceso y controles</h2><p>Completa cada campo y pulsa su botón. Después inicia sesión. Verifica la cuenta solo cuando Instagram haya terminado.</p><div id="controls" class="zbControls"></div></section><details><summary>Texto y diagnóstico de la página</summary><pre id="text" class="zbText"></pre></details>
<script src="/static/instagram-browser.js?v=33.3.64"></script></body></html>''', headers={'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex,nofollow', 'Content-Security-Policy': "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'"})

    @blueprint.post('/api/browser/instagram')
    def login_action():
        import secrets
        if not allowed_owner(): return jsonify(ok=False, reason='Titular no autorizado'), 403
        if not session.get('browser_csrf') or not secrets.compare_digest(request.headers.get('X-ZAR-Browser-CSRF', ''), session['browser_csrf']):
            return jsonify(ok=False, reason='CSRF inválido'), 403
        data = request.get_json(silent=True) or {}
        action = data.get('action')
        if action not in ('open', 'read', 'fill', 'click', 'verify') or len(json.dumps(data)) > 8000:
            return jsonify(ok=False, reason='Acción inválida'), 400
        try:
            if action == 'verify':
                result = verify()
                if result.get('authenticated'):
                    from . import reposnews, reposnews_inbox
                    from .holdings import transaction
                    with transaction('reposnews-editorial'):
                        state = reposnews.read()
                        # Only failed real items; never rewrite READY articles or duplicate proposals.
                        rows = [r for r in state.get('instagram_inbox', []) if r.get('status') in ('NEEDS_DISAMBIGUATION', 'FAILED_SOURCE', 'FAILED_RETRYABLE')]
                        if rows:
                            row = rows[-1]
                            row.update(status='RECEIVED', processing_state='RECOVERING', metadata_recovery=False,
                                       attempt_limit=row.get('attempts', 0)+1, retry_after=0)
                            reposnews.write(state)
                            result['reprocessing_item'] = row['id']
                return jsonify(result)
            payload = {'action': action}
            if action == 'open': payload['url'] = 'https://www.instagram.com/accounts/login/'
            if action in ('fill', 'click'):
                payload.update(control=data.get('control'), human_login=True)
                if action == 'fill': payload['value'] = str(data.get('value', ''))[:5000]
            result = browser().run(payload)
            result.pop('discovery', None)
            return jsonify(result)
        except Exception:
            return jsonify(ok=False, reason='No se completó la acción. Actualiza la pantalla; no se ha repetido.'), 400
