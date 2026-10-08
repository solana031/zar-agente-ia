import json
import mimetypes
import os
import re
import shutil
import threading
import uuid
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from .user_scope import safe_slug, get_current_user

DATA_DIR = Path(os.environ.get('ZAR_DATA_DIR', '/data'))

def _files_dir():
    d = DATA_DIR / 'users' / safe_slug() / 'files'
    d.mkdir(parents=True, exist_ok=True)
    return d

# v30.1.2: never freeze the active user at module-import time. Flask sets
# the user scope per request, so every read/write path must resolve dynamically.
def files_dir():
    return _files_dir()

# Kept as a compatibility alias for legacy imports. Internal code must use
# files_dir() so concurrent users never share the anonymous/import-time path.
FILES_DIR = None

def _meta_file():
    return _files_dir() / 'index.json'
LOCK = threading.RLock()
ALLOWED_CATEGORIES = {'sin_clasificar','facturas','finanzas','documentos','recibos','contratos','personal','fotos','otros'}
MAX_BYTES = int(os.environ.get('ZAR_MAX_UPLOAD_BYTES', str(500 * 1024 * 1024)))

class DuplicateFileError(ValueError):
    def __init__(self, item):
        self.item = item
        super().__init__('El archivo ya existe en la biblioteca de Zar.')


def _load():
    with LOCK:
        try:
            data = json.loads(_meta_file().read_text(encoding='utf-8'))
            return data if isinstance(data, list) else []
        except FileNotFoundError:
            return []
        except json.JSONDecodeError:raise ValueError('Índice de archivos dañado: se conserva para recuperación; no se sustituye por una biblioteca vacía.')


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
    persistent_storage()
    if not file_storage or not getattr(file_storage, 'filename', None):
        raise ValueError('No se recibió ningún archivo.')
    filename = _safe_name(file_storage.filename)
    mime = file_storage.mimetype or mimetypes.guess_type(filename)[0] or 'application/octet-stream'
    data = file_storage.read()
    if len(data) > MAX_BYTES:
        raise ValueError(f'El archivo supera el límite de {MAX_BYTES // (1024*1024)} MB.')
    sha256 = hashlib.sha256(data).hexdigest()
    existing = next((x for x in _load() if x.get('sha256') == sha256), None)
    if existing:
        raise DuplicateFileError(existing)
    file_id = uuid.uuid4().hex
    category = _guess_category(filename, mime)
    ext = Path(filename).suffix
    stored_name = f'{file_id}{ext}'
    path = _folder(category) / stored_name
    path.write_bytes(data)
    now = datetime.now(timezone.utc).isoformat()
    item = {
        'id': file_id,
        'owner_id':get_current_user(),'storage':'RAILWAY_VOLUME' if os.environ.get('RAILWAY_VOLUME_MOUNT_PATH') else 'LOCAL_PERSISTENT',
        'name': filename,
        'stored_name': stored_name,
        'mime': mime,
        'size': len(data),
        'category': category,
        'note': (note or '').strip(),
        'created_at': now,
        'updated_at': now,
        'analysis': {},
        'sha256': sha256,
        'indexing_status': 'pending',
        'indexing_error': '',
        'indexed_at': '',
    }
    with LOCK:
        all_items = _load(); all_items.append(item); _save(all_items)
    return item


def get_file(file_id):
    return next((x for x in _load() if x.get('id') == file_id and x.get('owner_id',get_current_user())==get_current_user()), None)


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
            hay = ' '.join(str(item.get(k,'')) for k in ('name','note','category','mime','retrieval_text','associated_contacts','associated_projects','associated_companies')).lower()
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
    path.unlink(missing_ok=True)
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
    out['indexing_status'] = item.get('indexing_status') or 'unknown'
    out['indexing_error'] = item.get('indexing_error') or ''
    out['indexed_at'] = item.get('indexed_at') or ''
    out['sha256'] = item.get('sha256') or ''
    out.setdefault('owner_id',get_current_user())
    out.setdefault('storage','RAILWAY_VOLUME' if os.environ.get('RAILWAY_VOLUME_MOUNT_PATH') else 'LOCAL_PERSISTENT')
    out['availability']='AVAILABLE' if FileStore().path(item['id']).is_file() else 'MISSING_BINARY'
    return out

def persistent_storage():
    mount=os.environ.get('RAILWAY_VOLUME_MOUNT_PATH','')
    if os.environ.get('RAILWAY_ENVIRONMENT_ID'):
        if not mount or not DATA_DIR.resolve().is_relative_to(Path(mount).resolve()) or not os.path.ismount(mount):
            raise ValueError('Almacenamiento persistente no verificado: no se guardarán archivos en el container efímero.')
    return {'storage':'RAILWAY_VOLUME' if mount else 'LOCAL_PERSISTENT','persistent':True,'root':str(DATA_DIR),'mount':mount or None}

class FileStore:
    """Scoped durable metadata and binaries; compatibility APIs above remain intact."""
    def save(self,name,data,mime='application/octet-stream',**metadata):
        from io import BytesIO
        from werkzeug.datastructures import FileStorage
        item=save_upload(FileStorage(stream=BytesIO(data),filename=name,content_type=mime))
        return self.metadata(item['id'],**metadata)
    def path(self,file_id):
        item=get_file(file_id)
        if not item:raise ValueError('Archivo no encontrado para este propietario.')
        if item.get('owner_id',get_current_user())!=get_current_user():raise ValueError('Propietario incorrecto.')
        path=files_dir()/item.get('category','sin_clasificar')/item.get('stored_name','')
        if not path.resolve().is_relative_to(files_dir().resolve()) or path.is_symlink():raise ValueError('Ruta de archivo inválida.')
        return path
    def read(self,file_id):
        path=self.path(file_id)
        if not path.is_file():raise ValueError('Metadata conservada, pero el binario histórico ya no está disponible.')
        data=path.read_bytes();item=get_file(file_id)
        if item.get('sha256') and hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('Checksum incorrecto; archivo no enviado.')
        return data
    def list(self,category=''):return list_files(category)
    def search(self,query,category=''):return search_files(query,category,500)
    def delete(self,file_id):self.path(file_id);return delete_file(file_id)
    def metadata(self,file_id,**changes):
        self.path(file_id)
        allowed={'report_template','chart_count','type','title','creator_agent','source_task','version','associated_contacts','associated_projects','associated_companies','associated_conversations','retrieval_text','drive_id','workspace_exports','name','category','note'}
        if set(changes)-allowed:raise ValueError('Campos de metadata no permitidos.')
        with LOCK:
            if 'category' in changes or 'note' in changes:update_file(file_id,changes.pop('category',None),changes.pop('note',None))
            items=_load();item=next(x for x in items if x['id']==file_id)
            if 'name' in changes:changes['name']=_safe_name(changes['name'])
            item.update(changes,owner_id=get_current_user(),updated_at=datetime.now(timezone.utc).isoformat());_save(items)
            return item
    def attachment(self,file_id):
        import base64
        item=get_file(file_id)
        if not item or int(item.get('size',0))>15*1024*1024:raise ValueError('Adjunto inexistente o superior a 15 MB.')
        return {'filename':item['name'],'mime':item['mime'],'data':base64.b64encode(self.read(file_id)).decode(),'file_id':file_id}
    def reconcile(self,previous_scope=None,legacy_owner=False):
        """Only current owner or the caller's original browser scope may be reconciled."""
        persistent_storage();recovered=0;missing=0
        sources=[]
        if previous_scope and previous_scope!=get_current_user():sources.append(DATA_DIR/'users'/safe_slug(previous_scope)/'files')
        if legacy_owner:sources.append(DATA_DIR/'files')
        with LOCK:
            items=_load();known={x['id'] for x in items};checksums={x.get('sha256') for x in items}
            for source in sources:
                if not source.resolve().is_relative_to(DATA_DIR.resolve()) or source.is_symlink():continue
                try:old=json.loads((source/'index.json').read_text(encoding='utf-8'))
                except (OSError,ValueError):old=[]
                for row in old:
                    src=source/row.get('category','sin_clasificar')/row.get('stored_name','')
                    existing=next((x for x in items if x['id']==row.get('id')),None)
                    if existing and self.path(existing['id']).is_file():continue
                    if not existing and row.get('sha256') and row.get('sha256') in checksums:continue
                    if not src.resolve().is_relative_to(source.resolve()) or src.is_symlink():continue
                    if not src.is_file():
                        if not existing and row.get('id'):
                            row=dict(row,owner_id=get_current_user(),category=row.get('category') if row.get('category') in ALLOWED_CATEGORIES else 'otros',stored_name=Path(row.get('stored_name','missing')).name)
                            items.append(row);known.add(row['id'])
                        continue
                    content=src.read_bytes();checksum=hashlib.sha256(content).hexdigest()
                    if row.get('sha256') and row['sha256']!=checksum:continue
                    category=row.get('category') if row.get('category') in ALLOWED_CATEGORIES else 'otros'
                    destination=_folder(category)/Path(row['stored_name']).name
                    if destination.exists():continue
                    shutil.copyfile(src,destination)
                    row=dict(row,category=category,stored_name=destination.name,sha256=checksum,owner_id=get_current_user(),storage='RAILWAY_VOLUME' if os.environ.get('RAILWAY_VOLUME_MOUNT_PATH') else 'LOCAL_PERSISTENT',recovered_from=safe_slug(previous_scope) if previous_scope else 'legacy')
                    if existing:existing.update(row)
                    else:items.append(row)
                    known.add(row['id']);checksums.add(checksum);recovered+=1
            paths={str(self.path(x['id']).resolve()) for x in _load()}
            paths.update(str((_files_dir()/x.get('category','sin_clasificar')/x.get('stored_name','')).resolve()) for x in items)
            for category in ALLOWED_CATEGORIES:
                folder=_files_dir()/category
                if not folder.exists():continue
                for path in folder.iterdir():
                    if not path.is_file() or path.is_symlink() or str(path.resolve()) in paths:continue
                    if not path.resolve().is_relative_to(files_dir().resolve()):continue
                    content=path.read_bytes();now=datetime.now(timezone.utc).isoformat()
                    items.append({'id':uuid.uuid4().hex,'name':path.name,'stored_name':path.name,'category':category,'mime':mimetypes.guess_type(path.name)[0] or 'application/octet-stream','size':len(content),'sha256':hashlib.sha256(content).hexdigest(),'owner_id':get_current_user(),'storage':'RAILWAY_VOLUME' if os.environ.get('RAILWAY_VOLUME_MOUNT_PATH') else 'LOCAL_PERSISTENT','created_at':now,'updated_at':now,'note':'Binario huérfano recuperado; nombre original no disponible.'});recovered+=1
            _save(items)
            missing+=sum(not self.path(x['id']).is_file() for x in items)
        return {'recovered':recovered,'missing_binaries':missing,'message':'Se conservan metadata y archivos disponibles; no se inventan binarios perdidos.','storage':persistent_storage()}
