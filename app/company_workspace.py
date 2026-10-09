"""Non-destructive company knowledge derived from the user's existing files."""
import json
import threading
import secrets
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request, session
from . import file_store
from . import company_knowledge
from .user_scope import get_current_user

blueprint = Blueprint('company_workspace', __name__)
LOCK = threading.RLock()
ACTIVE = threading.local()
PROFILE_FIELDS = ('name', 'activity', 'tax_id', 'address', 'notes')

def now():
    return datetime.now(timezone.utc).isoformat()

def path():
    return file_store.files_dir().parent / 'company_workspace.json'

@contextmanager
def transaction():
    """Serialize atomic revision updates across Gunicorn workers as well as threads."""
    with LOCK:
        if getattr(ACTIVE, 'locked', False):
            yield
            return
        with path().with_suffix('.lock').open('a+b') as handle:
            handle.seek(0, 2)
            if not handle.tell():
                handle.write(b'0'); handle.flush()
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX)
            ACTIVE.locked = True
            try: yield
            finally:
                ACTIVE.locked = False
                handle.seek(0)
                if os.name == 'nt': msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else: fcntl.flock(handle, fcntl.LOCK_UN)

def read():
    try:
        value = json.loads(path().read_text(encoding='utf-8'))
        if not isinstance(value, dict):
            raise ValueError('Base empresarial dañada; se conserva para recuperación.')
        return value
    except FileNotFoundError:
        return {'profile': {}, 'sources': [], 'history': [], 'revision': 0}

def write(data):
    file_store.persistent_storage()
    target = path()
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(target)

def classify(item):
    analysis = item.get('analysis') or {}
    if not isinstance(analysis, dict): analysis = {}
    text = ' '.join(str(x or '') for x in (item.get('name'), item.get('category'), analysis.get('document_type'))).lower()
    for kind, words in (('factura', ('factura', 'invoice')), ('cierre', ('cierre', 'closure')), ('contrato', ('contrato', 'contract')), ('informe', ('informe', 'report')), ('contabilidad', ('finanzas', 'contab', 'extracto'))):
        if any(word in text for word in words): return kind
    return 'documento'

def source(item, previous=None):
    analysis = item.get('analysis') or {}
    if not isinstance(analysis, dict): analysis = {}
    summary = analysis.get('summary') or analysis.get('description') or item.get('note') or ''
    excerpt = analysis.get('full_text') or item.get('retrieval_text') or ''
    # Recover lightweight local documents without invoking a model or modifying
    # their existing analysis. Binary/scanned documents remain explicitly pending.
    if not excerpt and str(item.get('name', '')).lower().endswith(('.txt', '.csv', '.md')):
        try:
            candidate = file_store.FileStore().path(item['id'])
            with candidate.open('rb') as handle:
                excerpt = handle.read(20000).decode('utf-8', errors='replace')
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    if not summary and excerpt:
        summary = ' '.join(str(excerpt).split())[:600]
    entities = {}
    for key in ('associated_companies', 'associated_contacts', 'associated_projects'):
        value = item.get(key) or analysis.get(key) or []
        entities[key] = value if isinstance(value, list) else [str(value)]
    return {'id': item['id'], 'name': item.get('name', 'Documento'), 'kind': (previous or {}).get('kind') or classify(item),
            'included': (previous or {}).get('included', True), 'note': (previous or {}).get('note', ''),
            'summary': str(summary)[:3000], 'excerpt': str(excerpt)[:5000], 'entities': entities,
            'status': 'disponible' if summary or excerpt else 'pendiente de extracción',
            'updated_at': item.get('updated_at'), 'created_at': item.get('created_at'),
            'download_url': file_store.download_url(item['id']), 'available': True}

def refresh():
    with transaction():
        data = read()
        previous = {row['id']: row for row in data.get('sources', [])}
        items = [row for row in file_store.list_files() if row.get('owner_id', get_current_user()) == get_current_user()]
        rows = [source(item, previous.get(item['id'])) for item in items]
        live = {row['id'] for row in rows}
        # Preserve source annotations and provenance even if a file was removed.
        rows.extend({**row, 'available': False} for key, row in previous.items() if key not in live)
        if rows != data.get('sources', []) or 'knowledge' not in data:
            data['sources'] = rows
            data['knowledge'] = company_knowledge.rebuild(rows, data.get('knowledge'))
            data['revision'] = data.get('revision', 0) + 1
            data['history'] = (data.get('history', []) + [{'timestamp': now(), 'action': 'Fuentes actualizadas', 'documents': len(items)}])[-100:]
            write(data)
        return data

@blueprint.get('/api/company-workspace')
def get_workspace():
    try: return jsonify(ok=True, workspace=refresh(), csrf=session.setdefault('business_csrf', secrets.token_urlsafe(32)))
    except (ValueError, OSError) as exc: return jsonify(ok=False, error=str(exc)), 400

@blueprint.post('/api/company-workspace')
def update_workspace():
    token = session.get('business_csrf')
    if not token or not secrets.compare_digest(request.headers.get('X-ZAR-Business-CSRF', ''), token):
        return jsonify(ok=False, error='Sesión inválida. Vuelve a abrir Workspace.'), 403
    body = request.get_json(silent=True) or {}
    try:
        with transaction():
            data = refresh()
            if body.get('revision') != data.get('revision', 0):
                return jsonify(ok=False, error='La base ha cambiado. Actualiza antes de guardar.'), 409
            action = body.get('action')
            if action == 'profile':
                incoming = body.get('profile') or {}
                if not isinstance(incoming, dict): raise ValueError('Perfil inválido.')
                data['profile'] = {key: str(incoming.get(key, '')).strip()[:5000] for key in PROFILE_FIELDS}
                label = 'Perfil empresarial editado'
            elif action == 'source':
                row = next((row for row in data['sources'] if row['id'] == body.get('id')), None)
                if row is None: raise ValueError('Fuente no encontrada.')
                if body.get('kind') not in {'factura', 'cierre', 'contrato', 'informe', 'contabilidad', 'documento'}: raise ValueError('Tipo inválido.')
                row.update(kind=body['kind'], included=body.get('included') is True, note=str(body.get('note') or '')[:3000])
                label = 'Fuente revisada: ' + row['name']
            elif action == 'rebuild':
                label = 'Base derivada reconstruida conservando perfil, notas y fuentes'
            else: raise ValueError('Acción no válida.')
            if action in {'source', 'rebuild'}:
                data['knowledge'] = company_knowledge.rebuild(data['sources'], data.get('knowledge'))
            data['revision'] += 1
            data['history'] = (data.get('history', []) + [{'timestamp': now(), 'action': label}])[-100:]
            write(data)
            return jsonify(ok=True, workspace=data)
    except (ValueError, OSError) as exc: return jsonify(ok=False, error=str(exc)), 400
