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
    key, path = ('GOOGLE_REDIRECT_URI', '/oauth2callback') if provider == 'google' else ('INSTAGRAM_REDIRECT_URI', '/api/reposnews/instagram/callback')
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

def page(provider, category, status=400):
    # No provider error text, OAuth code, state, session or token is reflected.
    logging.getLogger(__name__).info('oauth provider=%s category=%s http=%s correlation=%s', provider, category, status, secrets.token_hex(6))
    messages = {'CONNECTED':'Conexión completada. Vuelve a CUENTAS en ZAR.',
                'OAUTH_CANCELLED':'Conexión cancelada. Puedes volver a intentarlo desde CUENTAS.',
                'OWNER_SESSION_REQUIRED':'Abre CUENTAS en la sesión propietaria de ReposNews antes de conectar Instagram.',
                'OAUTH_STATE_INVALID':'La conexión ha caducado o ya se utilizó. Iníciala otra vez desde CUENTAS.'}
    response = make_response('<!doctype html><html lang="es"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ZAR · Conexión</title><body><h1>Conexión '+provider+'</h1><p>'+messages.get(category,'No se pudo completar la conexión. Vuelve a CUENTAS y reintenta.')+'</p><a href="/accounts">Volver a CUENTAS</a></body></html>', status)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response
