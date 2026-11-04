"""Scoped TikTok web authorization; tokens never leave the server."""
import hashlib
import json
import os
import secrets
import time
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlencode

import requests
from flask import abort, redirect, request, session
from . import oauth_transport as transport, oauth_vault

_LOCK=threading.RLock()


def configured():
    return bool(os.environ.get('TIKTOK_CLIENT_KEY', '').strip() and os.environ.get('TIKTOK_CLIENT_SECRET', '').strip())


def _path(scope):
    root = Path(os.environ.get('ZAR_DATA_DIR', '/data'))
    return root / 'tiktok' / (hashlib.sha256(scope.encode()).hexdigest() + '.json'), root


@contextmanager
def _locked(scope):
    # Token rotation must be serialized across workers without holding the
    # global business-state lock during a provider network request.
    path, _ = _path(scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, path.with_suffix('.lock').open('a+b') as handle:
        handle.seek(0, 2)
        if not handle.tell():
            handle.write(b'0');handle.flush()
        handle.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_LOCK,1)
        else:
            import fcntl
            fcntl.flock(handle,fcntl.LOCK_EX)
        try:yield
        finally:
            handle.seek(0)
            if os.name=='nt':msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(handle,fcntl.LOCK_UN)


def has_credentials(scope=None):
    from .user_scope import get_current_user
    return _path(scope or get_current_user())[0].exists() or bool(os.environ.get('TIKTOK_ACCESS_TOKEN','').strip())


def _exchange(**payload):
    response = requests.post('https://open.tiktokapis.com/v2/oauth/token/', data={
        'client_key': os.environ.get('TIKTOK_CLIENT_KEY', '').strip(),
        'client_secret': os.environ.get('TIKTOK_CLIENT_SECRET', '').strip(), **payload},
        timeout=25, allow_redirects=False)
    data = response.json()
    if not response.ok or data.get('error') or not all(data.get(k) for k in ('access_token', 'refresh_token', 'open_id')):
        raise ValueError('TIKTOK_AUTHORIZATION_REQUIRED')
    data['expires_at'] = time.time() + float(data['expires_in'])
    data['refresh_expires_at'] = time.time() + float(data['refresh_expires_in'])
    return data


def access_token(scope=None):
    from .user_scope import get_current_user
    scope = scope or get_current_user()
    path, root = _path(scope)
    if not path.exists():
        return os.environ.get('TIKTOK_ACCESS_TOKEN', '').strip()
    with _locked(scope):
        if not path.exists():
            return os.environ.get('TIKTOK_ACCESS_TOKEN', '').strip()
        # A saved authorization always wins over legacy environment credentials.
        data = oauth_vault.decode(path.read_text(encoding='utf-8'), root)
        if data.get('expires_at', 0) <= time.time() + 90:
            if not configured() or data.get('refresh_expires_at', 0) <= time.time():
                raise ValueError('TIKTOK_AUTHORIZATION_REQUIRED')
            refreshed = _exchange(grant_type='refresh_token', refresh_token=data['refresh_token'])
            if refreshed['open_id'] != data['open_id']:
                raise ValueError('TIKTOK_IDENTITY_CHANGED')
            oauth_vault.persist(path, json.dumps(refreshed), root)
            data = refreshed
        return data['access_token']


def register(app, scope_fn):
    @app.get('/connect/tiktok')
    def connect_tiktok():
        launch = session.get('accounts_oauth_launch', {})
        granted = launch.get('provider') == 'tiktok' and launch.get('expires', 0) > time.time()
        if session.get('zar_auth') is not True and not granted:
            abort(401)
        if not configured():
            return transport.page('TikTok', 'OAUTH_CONFIGURATION_REQUIRED', 409)
        try:
            callback = transport.callback('tiktok')
        except ValueError:
            return transport.page('TikTok', 'OAUTH_CONFIGURATION_REQUIRED', 409)
        state = secrets.token_urlsafe(32)
        transport.put('state:tiktok:' + state, {'scope': scope_fn(), 'callback': callback,
            'handoff': session.get('accounts_oauth_handoff')})
        response = redirect('https://www.tiktok.com/v2/auth/authorize/?' + urlencode({
            'client_key': os.environ['TIKTOK_CLIENT_KEY'].strip(), 'response_type': 'code',
            'scope': 'user.info.basic,video.publish', 'redirect_uri': callback,
            'state': state, 'disable_auto_auth': 1}))
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @app.get('/oauth/tiktok/callback')
    def tiktok_oauth_callback():
        pending = transport.get('state:tiktok:' + request.args.get('state', ''), consume=True)
        if not pending:
            return transport.page('TikTok', 'OAUTH_STATE_INVALID')
        category = 'ERROR'
        if request.args.get('error'):
            category = 'OAUTH_CANCELLED'
        elif request.args.get('code'):
            try:
                data = _exchange(grant_type='authorization_code', code=request.args['code'], redirect_uri=pending['callback'])
                path, root = _path(pending['scope'])
                with _locked(pending['scope']):
                    oauth_vault.persist(path, json.dumps(data), root)
                category = 'CONNECTED'
            except (ValueError, KeyError, OSError, requests.RequestException):
                category = 'ERROR'
        transport.complete(pending.get('handoff'), category, pending['scope'])
        return transport.page('TikTok', category, 200 if category == 'CONNECTED' else 400)
