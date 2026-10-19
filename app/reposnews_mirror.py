"""Derived static mirror. Primary publication and its approval remain in Railway."""
import hashlib
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path
import requests
from flask import jsonify, request, session
from . import holdings, reposnews as rn

MIRROR = 'https://solana031.github.io'
WORKFLOW = 'https://api.github.com/repos/solana031/solana031.github.io/actions/workflows/reposnews-mirror.yml/runs?per_page=1'
_wake = threading.Event()
_started = False


def _path():
    return rn._path().parent/'mirror-status.json'


def _read():
    try:
        return json.loads(_path().read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}


def _write(value):
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def public_manifest(data=None):
    """Only approved public snapshots, never current private revisions/owner data."""
    from .reposnews_automation import revision
    data = rn.read() if data is None else data
    articles = []
    for row in data.get('articles', []):
        if not row.get('published'):
            continue
        article = row.get('published_snapshot', row)
        if article.get('state') != 'PUBLISHED':
            continue
        slug = str(article.get('id', ''))
        if not re.fullmatch(r'[a-z0-9-]{1,80}', slug):
            continue
        articles.append({'id': slug, 'revision': revision(article),
                         'es': '/es/repositorios/'+slug+'/', 'en': '/en/repositories/'+slug+'/'})
    articles.sort(key=lambda a: a['id'])
    projection = {'articles': articles, 'legal': rn.public_legal_profile(data)}
    digest = hashlib.sha256(json.dumps(projection, sort_keys=True).encode()).hexdigest()
    return {'schema': 1, 'source_revision': digest, 'source_commit': os.getenv('RAILWAY_GIT_COMMIT_SHA', ''),
            'primary_status': 'PRIMARY_PUBLISHED', 'articles': articles,
            'published_articles_count': len(articles), 'request_nonce': _read().get('request_nonce', '')}


def parity(source, mirror):
    expected = {a['id']: a['revision'] for a in source['articles']}
    actual = {a['id']: a['revision'] for a in mirror.get('articles', [])}
    if (expected == actual and source['source_revision'] == mirror.get('source_revision')
            and source.get('source_commit', '') == mirror.get('source_commit', '')
            and mirror.get('mirror_policy') == 'noindex,follow'):
        return 'MIRROR_IN_SYNC'
    if actual and set(actual) != set(expected):
        return 'MIRROR_PARTIAL'
    return 'MIRROR_OUTDATED'


def wake():
    # No network or mirror failure can interrupt a primary editorial write.
    _wake.set()


def request_sync(scope):
    if rn.read().get('owner') != scope:
        raise ValueError('OWNER_REQUIRED')
    with holdings.transaction('reposnews-mirror'):
        state = _read()
        state.update(request_nonce=secrets.token_hex(12), requested_at=holdings._now(), status='OUTDATED')
        _write(state)
    wake()
    return view(scope)


def _notify(scope, kind, key, title, message, failed=False):
    from .notification_center import emit
    if kind == 'MIRROR_SYNC_SUCCESS':
        from . import identity_center
        with holdings.transaction(scope):
            data = holdings.read(scope)
            changed = False
            for row in identity_center.ensure(data)['human_actions']:
                if row.get('type') == 'MIRROR_SYNC_FAILED' and row.get('entity_id') == 'reposnews' and row.get('status') == 'ACTION_REQUIRED':
                    row.update(status='COMPLETED', actions=[{'label':'VER MIRROR','url':MIRROR},{'label':'VER PRODUCCIÓN','url':rn.ORIGIN}])
                    changed = True
            if changed:
                holdings.write(scope, data)
    link = '/?zar_workspace=sites#zarReposNewsMirror'
    actions = ([{'label': 'REINTENTAR MIRROR', 'url': link}, {'label': 'VER DETALLES', 'url': link}]
               if failed else [{'label': 'VER MIRROR', 'url': MIRROR}, {'label': 'VER PRODUCCIÓN', 'url': rn.ORIGIN}])
    emit(scope, kind, key, title, message, link if failed else MIRROR, 'reposnews', 'MIRROR', actions,
         details={'primary_status': 'PRIMARY_PUBLISHED'}, status='ACTION_REQUIRED' if failed else 'COMPLETED')


def _get(url):
    response = requests.get(url, timeout=20, headers={'User-Agent': 'ZAR-ReposNews-Mirror/1'})
    response.raise_for_status()
    if url.startswith(MIRROR) and not response.url.startswith(MIRROR+'/'):
        raise ValueError('MIRROR_REDIRECTED_OUTSIDE_STATIC_HOST')
    return response


def _head_asset(path):
    if not re.fullmatch(r'/media/reposnews/[\w-]+\.(?:png|svg|jpg|jpeg|webp|css|js)', path):
        raise ValueError('NONPUBLIC_MIRROR_ASSET')
    response = requests.head(MIRROR+path, timeout=20, allow_redirects=False)
    if response.status_code != 200:
        raise ValueError('MIRROR_ASSET_UNAVAILABLE')


def refresh():
    """Observe the independently deployed artifact; no Git credentials or DNS writes."""
    data = rn.read()
    scope = data.get('owner')
    if not scope:
        return
    source = public_manifest(data)
    with holdings.transaction('reposnews-mirror'):
        state = _read()
    before = state.get('source_revision')
    state.update(primary_status='PRIMARY_PUBLISHED', source_revision=source['source_revision'],
                 source_commit=source['source_commit'], published_articles_count=len(source['articles']), checked_at=holdings._now())
    state['primary_online'] = False
    try:
        _get(rn.ORIGIN+'/es/')
        state['primary_online'] = True
        remote = _get(MIRROR+'/build-manifest.json?mirror-check='+str(int(time.time()/120))).json()
        match = parity(source, remote)
        acknowledged = source['request_nonce'] == remote.get('request_nonce', '')
        state.update(parity=match, status='SYNCED' if match == 'MIRROR_IN_SYNC' and acknowledged else 'OUTDATED',
                     last_static_build=remote.get('last_static_build'), last_static_deploy=remote.get('last_static_deploy'),
                     mirror_revision=remote.get('source_revision'), deploy_status=remote.get('deploy_status', 'UNKNOWN'))
        if state['status'] == 'SYNCED':
            paths = ['/', '/es/', '/en/', '/sitemap.xml', '/robots.txt']
            if source['articles']:
                paths += [source['articles'][0]['es'], source['articles'][0]['en']]
            image = next((a for a in remote.get('asset_paths', []) if re.fullmatch(r'/media/reposnews/[\w-]+\.png', a)), None)
            if not image:
                raise ValueError('MIRROR_ASSET_MISSING')
            paths.append(image)
            if (state.get('verified_revision') != source['source_revision']
                    or state.get('verified_deploy') != remote.get('last_static_deploy')):
                for path in paths:
                    response = _get(MIRROR+path)
                    if path in {'/', '/es/', '/en/'} and 'content="noindex,follow"' not in response.text:
                        raise ValueError('MIRROR_NOINDEX_MISSING')
                for asset in remote.get('asset_paths', []):
                    _head_asset(asset)
                state.update(verified_at=holdings._now(), verified_revision=source['source_revision'], verified_deploy=remote.get('last_static_deploy'))
            state.update(recovery_status='REPOSNEWS_RECOVERY_READY', error=None)
            _notify(scope, 'MIRROR_SYNC_SUCCESS', 'mirror-synced:'+source['source_revision']+':'+remote.get('last_static_deploy', ''),
                    'ReposNews mirror actualizado', str(len(source['articles']))+' artículos sincronizados con GitHub Pages.')
        else:
            state['recovery_status'] = 'NOT_READY'
            if before != source['source_revision']:
                state['pending_since'] = holdings._now()
                _notify(scope, 'MIRROR_OUTDATED', 'mirror-outdated:'+source['source_revision'],
                        'ReposNews mirror pendiente', 'Producción publicada. La copia estática se actualizará en la próxima ejecución automática.')
            try:
                runs = _get(WORKFLOW).json().get('workflow_runs', [])
            except requests.HTTPError as error:
                if error.response is None or error.response.status_code != 404:
                    raise
                runs = []
            run = runs[0] if runs else {}
            # An older failed run must not mark a new primary publication failed.
            pending = state.get('requested_at') or state.get('pending_since') or ''
            completed_at = datetime.fromisoformat(run['updated_at'].replace('Z', '+00:00')) if run.get('updated_at') else None
            pending_at = datetime.fromisoformat(pending.replace('Z', '+00:00')) if pending else None
            if run.get('conclusion') in {'failure', 'cancelled', 'timed_out'} and completed_at and (not pending_at or completed_at >= pending_at):
                state.update(status='ERROR', deploy_status='MIRROR_SYNC_FAILED', error='GitHub Actions: '+run['conclusion'])
                _notify(scope, 'MIRROR_SYNC_FAILED', 'mirror-failed:'+str(run.get('id')), 'Artículo publicado, pero la copia estática no se ha sincronizado.',
                        'PRIMARY_PUBLISHED · MIRROR_SYNC_FAILED. Reintentar desde Sites.', True)
    except Exception as error:
        state.update(status='ERROR', deploy_status='MIRROR_SYNC_FAILED', recovery_status='NOT_READY', error=type(error).__name__)
        if state.get('parity') == 'MIRROR_IN_SYNC':
            state['parity'] = 'MIRROR_PARTIAL'
        _notify(scope, 'MIRROR_SYNC_FAILED', 'mirror-unavailable:'+source['source_revision'],
                'Artículo publicado, pero la copia estática no se ha sincronizado.', 'Producción conservada. Mirror no verificable.', True)
    with holdings.transaction('reposnews-mirror'):
        latest = _read()
        if latest.get('request_nonce', '') != source['request_nonce']:
            state.update(request_nonce=latest.get('request_nonce', ''), requested_at=latest.get('requested_at'), status='OUTDATED')
        _write(state)


def view(scope):
    if rn.read().get('owner') != scope:
        raise ValueError('OWNER_REQUIRED')
    state = _read()
    source = public_manifest()
    if state.get('source_revision') != source['source_revision']:
        state.update(status='OUTDATED', parity='MIRROR_OUTDATED')
    return state | {'primary_url': rn.ORIGIN, 'mirror_url': MIRROR, 'primary_provider': 'Railway',
                    'mirror_provider': 'GitHub Pages', 'published_articles_count': source['published_articles_count'],
                    'primary_status': 'PRIMARY_PUBLISHED', 'automatic': True, 'interval_minutes': 5}


def start_worker():
    global _started
    if _started:
        return
    _started = True
    def work():
        last_run = 0
        while True:
            if last_run:
                time.sleep(max(0, 120-(time.monotonic()-last_run)))
            try:
                refresh()
            except Exception:
                pass  # Primary publication is never failed by derived mirror monitoring.
            last_run = time.monotonic()
            _wake.wait(120)
            _wake.clear()
    threading.Thread(target=work, daemon=True, name='reposnews-mirror-monitor').start()


def register(app, scope_fn):
    @app.get('/api/reposnews/mirror')
    def mirror_state():
        if session.get('zar_auth') is not True:
            return jsonify(ok=False, error='AUTH_REQUIRED'), 401
        return jsonify(ok=True, csrf=session.setdefault('business_csrf', secrets.token_urlsafe(32)), mirror=view(scope_fn()))

    @app.post('/api/reposnews/mirror/sync')
    def mirror_sync():
        if session.get('zar_auth') is not True:
            return jsonify(ok=False, error='AUTH_REQUIRED'), 401
        csrf = session.get('business_csrf', '')
        if not csrf or not secrets.compare_digest(csrf, request.headers.get('X-ZAR-Business-CSRF', '')):
            return jsonify(ok=False, error='CSRF_REQUIRED'), 403
        return jsonify(ok=True, mirror=request_sync(scope_fn()))
