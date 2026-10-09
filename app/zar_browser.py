"""Scoped browser agent with encrypted state and unprivileged Chromium actor."""
import base64
import json
import os
import queue
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from flask import Blueprint, jsonify, request, session
from . import browser_network, file_store, oauth_vault
from .user_scope import get_current_user, safe_slug

blueprint = Blueprint('zar_browser', __name__)
LOCK = threading.RLock()
ACTORS = {}
PROXY = None


class Actor:
    def __init__(self, scope):
        global PROXY
        self.lock = threading.Lock()
        self.scope = scope
        self.last = time.monotonic()
        self.state_path = file_store.DATA_DIR / 'users' / safe_slug(scope) / 'browser_session.enc'
        file_store.persistent_storage()
        if PROXY is None:
            PROXY = browser_network.start_proxy()
        self.directory = tempfile.TemporaryDirectory(prefix='zar-browser-', ignore_cleanup_errors=True)
        os.chmod(self.directory.name, 0o755)
        env = {key: value for key, value in os.environ.items() if key in ('PATH', 'SYSTEMROOT', 'PLAYWRIGHT_BROWSERS_PATH', 'ZAR_BROWSER_EXECUTABLE')}
        env.update(ZAR_BROWSER_PROXY='http://127.0.0.1:%s' % PROXY.server_address[1], HOME=self.directory.name,
                   TMP=self.directory.name, TEMP=self.directory.name, USERPROFILE=self.directory.name,
                   LOCALAPPDATA=self.directory.name, APPDATA=self.directory.name,
                   PYTHONPATH=str(Path(__file__).resolve().parent.parent) + os.pathsep + os.environ.get('PYTHONPATH', ''))
        if os.name == 'nt':
            # Chrome checks the OS profile root when validating its isolated
            # temporary --user-data-dir. These are paths, never credentials.
            for key in ('USERPROFILE', 'LOCALAPPDATA', 'APPDATA', 'WINDIR', 'COMSPEC'):
                if key in os.environ:
                    env[key] = os.environ[key]
        options = {}
        if os.name != 'nt':
            import pwd
            account = pwd.getpwnam('zarbrowser')
            options.update(user=account.pw_uid, group=account.pw_gid, extra_groups=[])
            os.chown(self.directory.name, account.pw_uid, account.pw_gid)
        stored = oauth_vault.decode(self.state_path.read_text(encoding='utf-8'), file_store.DATA_DIR) if self.state_path.exists() else None
        self.process = subprocess.Popen([sys.executable, str(Path(__file__).with_name('browser_worker.py'))],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding='utf-8', cwd=self.directory.name, env=env, **options)
        self.responses = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        self.process.stdin.write(json.dumps({'storage': stored}) + '\n')
        self.process.stdin.flush()

    def _read(self):
        for line in self.process.stdout:
            try:
                self.responses.put(json.loads(line))
            except ValueError:
                pass
        self.responses.put({'ok': False, 'status': 'ACTION_REQUIRED', 'reason': 'Runtime Chromium indisponible; comprobar sandbox y dependencias.'})

    def run(self, data):
        with self.lock:
            self.last = time.monotonic()
            self.process.stdin.write(json.dumps(data) + '\n')
            self.process.stdin.flush()
            result = self.responses.get(timeout=50)
            storage = result.pop('storage', None)
            if storage is not None:
                oauth_vault.persist(self.state_path, json.dumps(storage), file_store.DATA_DIR)
            return result

    def close(self):
        try:
            self.process.stdin.write('{"action":"close"}\n')
            self.process.stdin.flush()
        except (OSError, ValueError):
            pass
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(self.process.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                self.process.kill()
            self.process.wait(timeout=5)
        self.directory.cleanup()


def actor(scope):
    with LOCK:
        for key, value in list(ACTORS.items()):
            if value.process.poll() is not None or time.monotonic() - value.last > 900:
                value.close()
                del ACTORS[key]
        if scope not in ACTORS:
            if len(ACTORS) >= 3:
                raise ValueError('Capacidad Browser ocupada')
            ACTORS[scope] = Actor(scope)
        return ACTORS[scope]


def operate(data):
    if not isinstance(data, dict):
        raise ValueError('Acción inválida')
    if data.get('action', 'read') not in {'prepare_account', 'open', 'read', 'back', 'forward', 'reload', 'page', 'click', 'fill', 'upload', 'download', 'close'}:
        raise ValueError('Acción inválida')
    if len(json.dumps(data)) > 12000:
        raise ValueError('Acción demasiado grande')
    action = data.get('action', 'read')
    if action == 'prepare_account':
        from .account_provisioner import prepare
        plan = prepare(get_current_user(), str(data.get('service', '')).upper())
        if plan.get('status') in ('VERIFIED', 'CONNECTED'):
            return plan
        page = operate({'action': 'open', 'url': plan['url']})
        page['account_check'] = plan
        return page
    if action == 'open':
        data = dict(data, url=browser_network.public_url(data.get('url', '')))
    scope = get_current_user()
    if action == 'close':
        with LOCK:
            existing = ACTORS.pop(scope, None)
            if existing:
                existing.close()
        return {'ok': True, 'status': 'READY', 'reason': 'Navegador cerrado; sesión cifrada conservada.'}
    browser_actor = actor(scope)
    temporary_upload = None
    if action == 'upload':
        if data.get('confirmed') is not True:
            return {'ok': False, 'status': 'ACTION_REQUIRED', 'reason': 'Confirmar destino y archivo antes de subir.'}
        store = file_store.FileStore()
        content = store.read(str(data.get('file_id', '')))
        if len(content) > 15 * 1024 * 1024:
            raise ValueError('Archivo demasiado grande')
        temporary_upload = Path(browser_actor.directory.name) / store.path(data['file_id']).name
        temporary_upload.write_bytes(content)
        temporary_upload.chmod(0o644)
        data = dict(data, path=str(temporary_upload))
    try:
        result = browser_actor.run(data)
    finally:
        if temporary_upload:
            temporary_upload.unlink(missing_ok=True)
    if result.get('file'):
        item = file_store.FileStore().save(result['name'], base64.b64decode(result.pop('file')))
        result.update(file_id=item['id'], download_url=file_store.download_url(item['id']))
    if data.get('save') and result.get('ok'):
        text = '%s\n%s\n\n%s' % (result.get('title'), result.get('url'), result.get('text'))
        item = file_store.FileStore().save('Browser-captura.txt', text.encode(), 'text/plain', retrieval_text=text)
        result['saved_file'] = {'id': item['id'], 'url': file_store.download_url(item['id'])}
    if result.get('status') == 'ACTION_REQUIRED':
        from . import holdings, identity_center
        with holdings.transaction(scope):
            state = holdings.read(scope)
            identity_center.queue(identity_center.ensure(state), 'BROWSER', 'HUMAN_INTERVENTION', result.get('reason', ''),
                result.get('url', ''), ['Abrir ZAR Browser. CAPTCHA, 2FA, credenciales o términos requieren intervención personal.'])
            holdings.write(scope, state)
    return result


@blueprint.get('/api/browser')
def browser_status():
    return jsonify(ok=True, csrf=session.setdefault('browser_csrf', secrets.token_urlsafe(32)),
        account='zaragente031@gmail.com', status='UNVERIFIED', session_active=get_current_user() in ACTORS,
        reason='Chromium se verifica al abrir una página. Sesión independiente de Google OAuth.')


@blueprint.post('/api/browser')
def browser_action():
    token = session.get('browser_csrf')
    if not token or not secrets.compare_digest(request.headers.get('X-ZAR-Browser-CSRF', ''), token):
        return jsonify(ok=False, status='ERROR', reason='Sesión inválida. Vuelve a abrir Browser.'), 403
    try:
        from . import cloud_auth, jev_decision
        if not cloud_auth.connected():
            return jsonify(ok=False, status='ACTION_REQUIRED', reason='Conecta tu sesión Google de ZAR antes de usar el navegador de servidor.'), 403
        data = request.get_json(silent=True) or {}
        action = data.get('action', 'read') if isinstance(data, dict) else ''
        decision = jev_decision.evaluate(get_current_user(), {'action': 'BROWSER_' + action.upper(), 'agent': 'BrowserAgent'})
        if decision['decision'] == 'DENY':
            return jsonify(ok=False, status='ERROR', reason='JEV bloquea la operación.'), 403
        if decision['decision'] == 'CONFIRM' and data.get('confirmed') is not True:
            return jsonify(ok=False, status='ACTION_REQUIRED', reason='JEV requiere confirmación separada.'), 409
        return jsonify(operate(data))
    except (ValueError, OSError, queue.Empty, KeyError):
        return jsonify(ok=False, status='ERROR', reason='URL, runtime o almacenamiento no disponible. No se ha reintentado la acción.'), 400
