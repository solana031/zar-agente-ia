"""Short-lived, encrypted, single-use OAuth handoffs across browser cookie jars."""
import json
import logging
import os
import secrets
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlsplit
from flask import make_response
from html import escape
from . import oauth_vault

TTL = 600

def configure_proxy(app):
    if os.environ.get('RAILWAY_ENVIRONMENT_ID'):
        from werkzeug.middleware.proxy_fix import ProxyFix
        # Railway's final ingress overwrites X-Forwarded-Proto. Do not trust
        # forwarded host/address/port, and never enable proxy trust locally.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=0, x_proto=1, x_host=0, x_port=0, x_prefix=0)
        app.config['PREFERRED_URL_SCHEME'] = 'https'

def origin():
    value = os.environ.get('PUBLIC_BASE_URL', '').strip().rstrip('/')
    if not value:
        value = os.environ.get('GOOGLE_REDIRECT_URI', '').removesuffix('/oauth2callback').rstrip('/')
    if not value:
        if os.environ.get('RAILWAY_ENVIRONMENT_ID'):
            raise ValueError('PUBLIC_BASE_URL_REQUIRED')
        return 'http://127.0.0.1:8765'
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise ValueError('PUBLIC_BASE_URL_INVALID')
    return value

def callback(provider):
    key, path = {'google': ('GOOGLE_REDIRECT_URI', '/oauth2callback'),
                 'instagram': ('INSTAGRAM_REDIRECT_URI', '/api/reposnews/instagram/callback'),
                 'tiktok': ('TIKTOK_REDIRECT_URI', '/oauth/tiktok/callback')}[provider]
    value = os.environ.get(key, '').strip() or origin() + path
    parsed = urlsplit(value)
    if parsed.netloc != urlsplit(origin()).netloc or parsed.scheme != urlsplit(origin()).scheme or parsed.query or parsed.fragment or parsed.path != path:
        raise ValueError('OAUTH_CALLBACK_INVALID')
    return value

def _db():
    root = Path(os.environ.get('ZAR_DATA_DIR', '/data'))
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / 'oauth_transactions.sqlite3', timeout=10)
    (root / 'oauth_transactions.sqlite3').chmod(0o600)
    db.execute('CREATE TABLE IF NOT EXISTS transactions (id TEXT PRIMARY KEY, expires REAL, payload TEXT)')
    return root, db

def put(key, value, ttl=TTL):
    root, db = _db()
    with db:
        db.execute('DELETE FROM transactions WHERE expires < ?', (time.time(),))
        db.execute('INSERT OR REPLACE INTO transactions VALUES (?,?,?)',
                   (key, time.time()+ttl, oauth_vault.encode(json.dumps(value), root)))
    db.close()

def get(key, consume=False):
    root, db = _db()
    try:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT expires,payload FROM transactions WHERE id=?', (key,)).fetchone()
        if consume:
            db.execute('DELETE FROM transactions WHERE id=?', (key,))
        db.commit()
        return oauth_vault.decode(row[1], root) if row and row[0] >= time.time() else {}
    finally:
        db.close()

def begin(scope, provider, path):
    ident = secrets.token_urlsafe(32)
    payload = dict(scope=scope, provider=provider, path=path, status='PENDING')
    put('launch:'+ident, payload)
    put('result:'+ident, payload)
    return ident

def complete(ident, status, scope=None):
    if not ident:
        return
    row = get('result:'+ident)
    if row and row['status'] == 'PENDING':
        row.update(status=status, result_scope=scope)
        put('result:'+ident, row)

def prevent_embedded_oauth():
    from flask import request
    ua=request.headers.get('User-Agent','')
    import re
    webview='Android' in ua and bool(re.search(r'; wv[);]',ua))
    if request.headers.get('Sec-Fetch-Dest')!='iframe' and not webview:return None
    provider={'/connect/google':'Google','/connect/youtube':'YouTube','/connect/tiktok':'TikTok','/api/reposnews/instagram/connect':'Instagram'}.get(request.path)
    if request.path.startswith('/oauth/accounts/start/'):provider='la cuenta'
    if not provider:return None
    # No state is issued and no one-use handoff is consumed inside an iframe.
    url=origin()+request.full_path.rstrip('?')
    message='Este enlace se ha abierto dentro de una app. Usa su menú para abrirlo en Chrome. No vuelvas a pulsar el enlace dentro de esta misma pantalla.' if webview else 'La autorización debe abrirse en una ventana externa al panel de CUENTAS. Continúa en tu navegador para seleccionar la cuenta.'
    action='<button type="button" id="copyOAuthLink">COPIAR ENLACE SEGURO</button>' if webview else '<a class="oauthPrimary" data-oauth-fallback="1" href="'+escape(url,quote=True)+'" target="_top">CONTINUAR EN EL NAVEGADOR</a>'
    response=make_response('<!doctype html><html lang="es"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Conectar cuenta · ZAR</title><link rel="stylesheet" href="/static/accounts.css?v=connections-20261104"><body><main class="accounts oauthHelp"><a class="brand" href="/accounts" target="_top">ZAR / CONEXIONES</a><section class="card"><span class="oauthBadge">AUTORIZACIÓN SEGURA</span><h1>Continúa en Chrome</h1><p>'+message+'</p>'+action+'<details><summary>Ver enlace seguro</summary><input id="oauthSafeLink" aria-label="Enlace HTTPS de autorización" readonly value="'+escape(url,quote=True)+'"></details><p id="notice" role="status"></p><a href="/accounts" target="_top">Volver a CUENTAS</a></section></main><script src="/static/oauth-help.js?v=33.3.127"></script></body></html>')
    if not webview:response.set_data(response.get_data(as_text=True).replace('</body>', '<script src="/static/oauth-launcher.js?v=connections-20261104"></script></body>'))
    response.headers['Cache-Control']='no-store';response.headers['Referrer-Policy']='no-referrer'
    return response


def page(provider, category, status=400):
    from flask import session
    # No provider error text, OAuth code, state, session or token is reflected.
    logging.getLogger(__name__).info('oauth provider=%s category=%s http=%s correlation=%s', provider, category, status, secrets.token_hex(6))
    messages = {'OAUTH_CONFIGURATION_REQUIRED':'Falta configurar la aplicación o su dirección de retorno en el servidor. Revisa los detalles de la cuenta en ZAR.',
                'PROVIDER_BLOCKED':'Meta bloquea el acceso a su API. Revisa la confirmación de tu cuenta en Meta Developers; no repitas OAuth mientras siga bloqueada.',
                'CONNECTED':'Conexión completada. Vuelve a CUENTAS en ZAR.',
                'OAUTH_CANCELLED':'Conexión cancelada. Puedes volver a intentarlo desde CUENTAS.',
                'OWNER_SESSION_REQUIRED':'Abre CUENTAS en la sesión propietaria de ReposNews antes de conectar Instagram.',
                'OAUTH_STATE_INVALID':'La conexión ha caducado o ya se utilizó. Iníciala otra vez desde CUENTAS.'}
    success='<p>Cuenta conectada correctamente.</p>' if category=='CONNECTED' else ''
    response = make_response('<!doctype html><html lang="es"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ZAR · Conexión</title><link rel="stylesheet" href="/static/accounts.css"><body data-oauth-provider="'+escape(provider.lower(),quote=True)+'" data-oauth-status="'+escape(category,quote=True)+'"><main class="accounts"><h1>Conexión '+escape(provider)+'</h1>'+success+'<p>'+messages.get(category,'No se pudo completar la conexión. Vuelve a CUENTAS y reintenta.')+'</p><a href="/accounts" target="_top">Volver a CUENTAS</a></main><script src="/static/oauth-callback.js?v=33.3.127"></script></body></html>', status)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    if session.get('zar_auth') is True:
        response.set_data(response.get_data(as_text=True).replace('data-oauth-provider=', 'data-oauth-return="1" data-oauth-provider=',1))
    return response
