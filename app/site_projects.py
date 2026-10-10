"""SiteProject CRUD/import/SEO over the existing Sites registry and files."""
import io
import re
import stat
import zipfile
from pathlib import PurePosixPath
from html.parser import HTMLParser
from . import holdings, sites_company

EXTENSIONS = {'.html','.htm','.css','.js','.png','.jpg','.jpeg','.gif','.webp','.svg','.ico','.txt','.xml','.woff','.woff2'}
MAX_BYTES = 20 * 1024 * 1024


def _files(files):
    output = {}
    for filename, content in files:
        if len(content) > MAX_BYTES:
            raise ValueError('Archivo supera 20 MB.')
        if filename.lower().endswith('.zip'):
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if len(archive.infolist()) > 200:
                    raise ValueError('ZIP: máximo 200 archivos.')
                for entry in archive.infolist():
                    if entry.is_dir():
                        continue
                    if stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1:
                        raise ValueError('ZIP: enlaces/cifrado no admitidos.')
                    if entry.file_size > MAX_BYTES or sum(len(x) for x in output.values()) + entry.file_size > MAX_BYTES:
                        raise ValueError('ZIP expandido supera 20 MB.')
                    _accept(output, entry.filename, archive.read(entry))
        else:
            _accept(output, filename, content)
    return output


def _accept(output, name, content):
    path = PurePosixPath(name)
    if '\\' in name or ':' in name or path.is_absolute() or '..' in path.parts or any(x.startswith('.') for x in path.parts) or path.suffix.lower() not in EXTENSIONS:
        raise ValueError('Ruta/tipo de archivo no admitido: solo proyectos estáticos HTML/CSS/JS e imágenes.')
    if str(path) in output:
        raise ValueError('Archivo duplicado en proyecto.')
    output[str(path)] = content
    if len(output) > 200 or sum(len(x) for x in output.values()) > MAX_BYTES:
        raise ValueError('Proyecto supera 200 archivos/20 MB.')


def create(scope, data, files=()):
    if not isinstance(data, dict):
        raise ValueError('Campos de proyecto requeridos.')
    name, topic = str(data.get('name','')).strip()[:120], str(data.get('topic','')).strip()[:1000]
    domain = str(data.get('domain','')).strip().lower()
    if domain and not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', domain):
        raise ValueError('Introduce dominio sin protocolo/ruta.')
    code = str(data.get('code') or '')
    imported = _files(files)
    if code:
        _accept(imported,'index.html',code.encode('utf-8'))
    if not name or not (topic or domain or imported):
        raise ValueError('Nombre y temática, dominio o archivos requeridos.')
    if imported and 'index.html' not in imported:
        raise ValueError('Proyecto estático debe contener index.html en la raíz del ZIP.')
    slug = sites_company._slug(name)
    row = {'id':slug, 'slug':slug, 'name':name, 'topic':topic, 'language':str(data.get('language') or 'es')[:30],
        'country':str(data.get('country') or 'ES')[:40], 'domain':domain or None,
        'source_kind':'UPLOAD' if imported else 'DOMAIN' if domain else 'IDEA',
        'state':'READY' if imported else 'DRAFT', 'created_at':holdings._now(), 'updated_at':holdings._now(),
        'relative_url':'/holdings/site/'+slug+'/' if imported else None,
        'adsense_status':'ACTION_REQUIRED', 'deployment':None, 'files':list(imported), 'agents':[],
        'metrics':None, 'error':None, 'content_review_required':True, 'safe_preview':True}
    with holdings.transaction(scope):
        rows = sites_company._read_registry(scope)
        if len(rows) >= 200:
            raise ValueError('Límite de proyectos: 200.')
        root = sites_company._public_root() / slug
        for filename, content in imported.items():
            target = root / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        rows.append(row)
        sites_company._write_registry(scope,rows)
    return row


def get(scope, project_id):
    return next(x for x in sites_company._read_registry(scope) if x['id']==project_id)


def patch(scope, project_id, **values):
    with holdings.transaction(scope):
        rows = sites_company._read_registry(scope)
        row = next(x for x in rows if x['id']==project_id)
        row.update(values,updated_at=holdings._now())
        sites_company._write_registry(scope,rows)
        return row


def build(scope, project_id):
    project = get(scope,project_id)
    if project['source_kind'] != 'IDEA':
        raise ValueError('Importación/dominio: conserva archivos existentes; no se sobrescriben con una web de idea.')
    patch(scope,project_id,state='BUILDING',error=None)
    try:
        site = sites_company.build_site(scope,project['topic'],project['name'],queue_promotion=False,project=project)
        return site
    except Exception:
        patch(scope,project_id,state='ERROR',error='Construcción interrumpida; proyecto conservado.')
        raise ValueError('No se pudo construir el proyecto.') from None


class SEOInspector(HTMLParser):
    def __init__(self):
        super().__init__(); self.title=False; self.description=False; self.h1=0; self.images=0; self.alt=0; self.viewport=False; self.canonical=False; self.opengraph=False; self.twitter=False
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='title': self.title=True
        if tag=='h1': self.h1+=1
        if tag=='meta' and a.get('name')=='description': self.description=bool(a.get('content'))
        if tag=='meta' and a.get('name')=='viewport': self.viewport=True
        if tag=='img': self.images+=1; self.alt+=int('alt' in a)
        if tag=='link' and a.get('rel')=='canonical': self.canonical=bool(a.get('href'))
        if tag=='meta' and a.get('property')=='og:title': self.opengraph=bool(a.get('content'))
        if tag=='meta' and a.get('name')=='twitter:card': self.twitter=bool(a.get('content'))


def analyze(scope, project_id):
    project=get(scope,project_id)
    file=sites_company._public_root()/project['slug']/'index.html'
    if not file.exists():
        raise ValueError('Dominio inventariado: importa el HTML/proyecto para análisis local; no se descargan URLs arbitrarias.')
    parser=SEOInspector();parser.feed(file.read_text(encoding='utf-8',errors='replace'))
    checks={'title':parser.title,'description':parser.description,'single_h1':parser.h1==1,
            'viewport':parser.viewport,'images_with_alt':parser.alt==parser.images,'canonical':parser.canonical,
            'opengraph':parser.opengraph,'twitter_card':parser.twitter,
            'sitemap':(file.parent/'sitemap.xml').exists(),'robots':(file.parent/'robots.txt').exists()}
    result={'source':'local_html','checked_at':holdings._now(),'checks':checks,
        'score':round(100*sum(checks.values())/len(checks)),
        'issues':[{'check':k,'priority':'HIGH' if k in {'title','description','single_h1'} else 'MEDIUM','fix':'Completar '+k+' y volver a analizar'} for k,v in checks.items() if not v],
        'next_steps':[k for k,v in checks.items() if not v], 'ranking_prediction':None}
    patch(scope,project_id,seo=result)
    return result


def preview_headers(response):
    # Imported HTML executes in an opaque sandbox, never with ZAR's origin authority.
    response.headers['Content-Security-Policy']="sandbox allow-scripts; default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'none'; form-action 'none'; base-uri 'none'"
    response.headers['X-Content-Type-Options']='nosniff'
    return response
