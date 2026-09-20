import json
import mimetypes
import os
import re
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from .user_scope import safe_slug

DATA_DIR = Path(os.environ.get('ZAR_DATA_DIR', '/data'))
FILES_DIR = DATA_DIR / 'files'
META_FILE = FILES_DIR / 'index.json'

def _files_dir():
    d = DATA_DIR / 'users' / safe_slug() / 'files'
    d.mkdir(parents=True, exist_ok=True)
    return d

def _meta_file():
    return _files_dir() / 'index.json'
LOCK = threading.RLock()
ALLOWED_CATEGORIES = {'sin_clasificar','facturas','finanzas','documentos','recibos','contratos','personal','fotos','otros'}
MAX_BYTES = int(os.environ.get('ZAR_MAX_UPLOAD_BYTES', str(500 * 1024 * 1024)))


def _load():
    with LOCK:
        try:
            data = json.loads(_meta_file().read_text(encoding='utf-8'))
            return data if isinstance(data, list) else []
        except (FileNotFoundError, json.JSONDecodeError):
            return []


def _save(data):
    with LOCK:
        _files_dir().mkdir(parents=True, exist_ok=True)
        tmp = _meta_file().with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(_meta_file())


def _safe_name(name):
    name = Path(name or 'archivo').name
    name = re.sub(r'[^\w.()\-áéíóúüñÁÉÍÓÚÜÑ ]+', '_', name, flags=re.UNICODE).strip() or 'archivo'
    return name[:180]


def _folder(category):
    category = category if category in ALLOWED_CATEGORIES else 'sin_clasificar'
    folder = _files_dir() / category
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _guess_category(name, mime):
    text = (name or '').lower()
    if any(w in text for w in ('factura','invoice')):
        return 'facturas'
    if any(w in text for w in ('recibo','ticket','albaran','albarán')):
        return 'recibos'
    if any(w in text for w in ('contrato','contract')):
        return 'contratos'
    if any(w in text for w in ('nomina','nómina','bank','banco','extracto')):
        return 'finanzas'
    if mime and mime.startswith('image/'):
        return 'fotos'
    if mime in {'application/pdf','application/msword','application/vnd.openxmlformats-officedocument.wordprocessingml.document','text/plain','text/csv'}:
        return 'documentos'
    return 'sin_clasificar'


def save_upload(file_storage, note=''):
    if not file_storage or not getattr(file_storage, 'filename', None):
        raise ValueError('No se recibió ningún archivo.')
    filename = _safe_name(file_storage.filename)
    mime = file_storage.mimetype or mimetypes.guess_type(filename)[0] or 'application/octet-stream'
    data = file_storage.read()
    if len(data) > MAX_BYTES:
        raise ValueError(f'El archivo supera el límite de {MAX_BYTES // (1024*1024)} MB.')
    file_id = uuid.uuid4().hex
    category = _guess_category(filename, mime)
    ext = Path(filename).suffix
    stored_name = f'{file_id}{ext}'
    path = _folder(category) / stored_name
    path.write_bytes(data)
    now = datetime.now(timezone.utc).isoformat()
    item = {
        'id': file_id,
        'name': filename,
        'stored_name': stored_name,
        'mime': mime,
        'size': len(data),
        'category': category,
        'note': (note or '').strip(),
        'created_at': now,
        'updated_at': now,
        'analysis': {},
    }
    with LOCK:
        all_items = _load(); all_items.append(item); _save(all_items)
    return item


def get_file(file_id):
    return next((x for x in _load() if x.get('id') == file_id), None)


def list_files(category=''):
    items = list(reversed(_load()))
    if category and category in ALLOWED_CATEGORIES:
        items = [x for x in items if x.get('category') == category]
    return items


def search_files(query='', category='', limit=20):
    query = (query or '').strip().lower()
    items = list_files(category)
    if query:
        tokens = [t for t in re.findall(r'\w+', query, re.UNICODE) if len(t) > 1]
        scored = []
        for item in items:
            hay = ' '.join(str(item.get(k,'')) for k in ('name','note','category','mime')).lower()
            score = sum(2 if tok in item.get('name','').lower() else 1 for tok in tokens if tok in hay)
            if score:
                scored.append((score,item))
        scored.sort(key=lambda p: (p[0], p[1].get('created_at','')), reverse=True)
        items = [x for _,x in scored]
    return items[:max(1, min(int(limit or 20), 500))]


def update_file(file_id, category=None, note=None):
    item = get_file(file_id)
    if not item:
        return None
    old_cat = item.get('category','sin_clasificar')
    if category:
        category = category.strip().lower().replace(' ', '_')
        aliases = {'factura':'facturas','invoice':'facturas','recibo':'recibos','documento':'documentos','foto':'fotos','personal':'personal','contrato':'contratos','finanzas':'finanzas','otros':'otros'}
        category = aliases.get(category, category)
        if category not in ALLOWED_CATEGORIES:
            category = 'otros'
    else:
        category = old_cat
    item['category'] = category
    if note is not None:
        item['note'] = note.strip()
    item['updated_at'] = datetime.now(timezone.utc).isoformat()
    if category != old_cat:
        old_path = _folder(old_cat) / item['stored_name']
        new_path = _folder(category) / item['stored_name']
        if old_path.exists():
            shutil.move(str(old_path), str(new_path))
    data = _load()
    for i, x in enumerate(data):
        if x.get('id') == file_id:
            data[i] = item
            break
    _save(data)
    return item


def delete_file(file_id):
    item = get_file(file_id)
    if not item:
        return False
    path = _folder(item.get('category','sin_clasificar')) / item.get('stored_name','')
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass
    data = [x for x in _load() if x.get('id') != file_id]
    _save(data)
    return True


def download_url(file_id):
    return f'/api/files/{quote(file_id, safe="")}/download'


def public_item(item):
    if not item:
        return None
    out = dict(item)
    out['download_url'] = download_url(item['id'])
    out['extension'] = Path(item.get('name','')).suffix.lower().lstrip('.') or 'sin extensión'
    out['size_bytes'] = int(item.get('size') or 0)
    out['zar_path'] = f"Archivos de Zar / {item.get('category','sin_clasificar')} / {item.get('name','archivo')}"
    return out
