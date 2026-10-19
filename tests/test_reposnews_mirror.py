import copy
import json
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone
import pytest
from flask import Flask
from app import reposnews as rn, reposnews_mirror as mirror
from tools import reposnews_mirror_sync as runner


@pytest.fixture
def editorial(tmp_path, monkeypatch):
    monkeypatch.setattr(rn, '_path', lambda: tmp_path/'editorial.json')
    snapshot = {'id': 'approved', 'state': 'PUBLISHED', 'title_es': 'Approved ES', 'title_en': 'Approved EN',
                'body_es': 'Public ES', 'body_en': 'Public EN', 'sources': ['https://example.org/official']}
    data = {'owner': 'owner', 'articles': [snapshot | {'published': True, 'published_snapshot': copy.deepcopy(snapshot)}],
            'legal': {'address': 'PRIVATE ADDRESS', 'tax_id': 'PRIVATE TAX'}}
    rn.write(data)
    return data


def test_only_published_snapshots_and_no_private_fields(editorial):
    original = mirror.public_manifest()
    editorial['articles'][0].update(body_es='PRIVATE REVISION', state='READY_PRIVATE')
    editorial['articles'] += [{'id': 'draft', 'state': 'READY_PRIVATE', 'published': False, 'body_es': 'PRIVATE NOTE'},
                             {'id': 'cancelled', 'state': 'CANCELLED', 'published': False}]
    rn.write(editorial)
    source = mirror.public_manifest()
    assert source['source_revision'] == original['source_revision']
    assert source['published_articles_count'] == 1
    assert [a['id'] for a in source['articles']] == ['approved']
    assert 'PRIVATE' not in json.dumps(source) and 'owner' not in json.dumps(source)


def test_approved_public_revision_change_changes_source(editorial):
    before = mirror.public_manifest()
    editorial['articles'][0]['published_snapshot']['body_es'] = 'Approved updated public text'
    rn.write(editorial)
    assert mirror.public_manifest()['source_revision'] != before['source_revision']


def test_parity_distinguishes_outdated_partial_and_synced(editorial):
    source = mirror.public_manifest()
    remote = source | {'mirror_policy': 'noindex,follow'}
    assert mirror.parity(source, remote) == 'MIRROR_IN_SYNC'
    assert mirror.parity(source, remote | {'source_revision': 'old'}) == 'MIRROR_OUTDATED'
    assert mirror.parity(source, remote | {'articles': [{'id': 'different', 'revision': 'old'}]}) == 'MIRROR_PARTIAL'
    assert mirror.parity(source, remote | {'mirror_policy': 'index,follow'}) == 'MIRROR_OUTDATED'


def test_mirror_success_notifies_and_recovery_is_ready(editorial, monkeypatch):
    source = mirror.public_manifest()
    remote = source | {'mirror_policy': 'noindex,follow', 'asset_paths': ['/media/reposnews/home.png'],
                       'last_static_build': '2026-10-19', 'last_static_deploy': '2026-10-19', 'deploy_status': 'DEPLOYED'}
    events = []
    monkeypatch.setattr(mirror, '_notify', lambda *a, **k: events.append(a))
    monkeypatch.setattr(mirror, '_get', lambda url: SimpleNamespace(json=lambda: remote, text='<meta name="robots" content="noindex,follow">'))
    checked_assets = []
    monkeypatch.setattr(mirror, '_head_asset', lambda path: checked_assets.append(path))
    mirror.refresh()
    state = mirror.view('owner')
    assert state['status'] == 'SYNCED' and state['parity'] == 'MIRROR_IN_SYNC'
    assert state['recovery_status'] == 'REPOSNEWS_RECOVERY_READY'
    assert events[0][1] == 'MIRROR_SYNC_SUCCESS'
    assert checked_assets == ['/media/reposnews/home.png']
    mirror.refresh()
    assert checked_assets == ['/media/reposnews/home.png']  # once per verified deployment


def test_mirror_failure_never_fails_primary_publication(editorial, monkeypatch):
    before = rn.read()
    def fail(url): raise ConnectionError('offline')
    events = []
    monkeypatch.setattr(mirror, '_get', fail)
    monkeypatch.setattr(mirror, '_notify', lambda *a, **k: events.append(a))
    mirror.refresh()
    state = mirror.view('owner')
    assert rn.read() == before
    assert state['primary_status'] == 'PRIMARY_PUBLISHED'
    assert state['deploy_status'] == 'MIRROR_SYNC_FAILED'
    assert events[0][1] == 'MIRROR_SYNC_FAILED'


def test_manual_sync_authenticated_csrf_and_no_second_confirmation(editorial):
    app = Flask(__name__)
    app.secret_key = 'offline-tests-only'
    mirror.register(app, lambda: 'owner')
    client = app.test_client()
    assert client.post('/api/reposnews/mirror/sync').status_code == 401
    with client.session_transaction() as session:
        session['zar_auth'] = True
        session['business_csrf'] = 'csrf'
    assert client.post('/api/reposnews/mirror/sync').status_code == 403
    before = mirror.public_manifest()
    response = client.post('/api/reposnews/mirror/sync', headers={'X-ZAR-Business-CSRF': 'csrf'})
    assert response.status_code == 200 and response.json['mirror']['status'] == 'OUTDATED'
    after = mirror.public_manifest()
    assert after['request_nonce'] != before['request_nonce']
    assert after['source_revision'] == before['source_revision']
    assert rn.read() == editorial


def test_mirror_build_noindex_retains_production_canonical(editorial, monkeypatch, tmp_path):
    source = mirror.public_manifest()
    source['articles'][0]['revision'] = source['articles'][0]['revision']
    monkeypatch.setattr(runner, 'manifest', lambda fetch: copy.deepcopy(source))
    def build(output, fetch):
        root = Path(output)
        html = '<head><meta name="robots" content="index,follow"><link rel="canonical" href="https://www.reposnews.com/es/repositorios/approved/"><link href="https://www.reposnews.com/en/repositories/approved/"></head>'
        for name in ['index.html', 'es/index.html', 'en/index.html', 'es/repositorios/approved/index.html', 'en/repositories/approved/index.html']:
            page = root/name;page.parent.mkdir(parents=True, exist_ok=True);page.write_text(html)
        media = root/'media/reposnews';media.mkdir(parents=True);(media/'home.png').write_bytes(b'public')
        return {'published_articles': 1, 'status': 'STATIC_HOST_READY', 'backend_required': False}
    monkeypatch.setattr(runner, 'build_reposnews_static', build)
    output = tmp_path/'build'
    metadata = runner.build_mirror(output)
    assert metadata['mirror_policy'] == 'noindex,follow'
    assert metadata['source_revision'] == source['source_revision']
    assert metadata['articles'] == source['articles']
    assert metadata['asset_paths'] == ['/media/reposnews/home.png']
    for page in output.rglob('*.html'):
        assert 'content="noindex,follow"' in page.read_text()
        assert 'https://www.reposnews.com/es/repositorios/approved/' in page.read_text()


def test_runner_rejects_primary_not_published_before_build():
    with pytest.raises(ValueError, match='PRIMARY_PUBLISHED_MANIFEST_REQUIRED'):
        runner.manifest(lambda url: json.dumps({'primary_status': 'FAILED'}).encode())


def test_old_workflow_failure_does_not_fail_new_primary(editorial, monkeypatch):
    events = []
    run = {'id': 123, 'conclusion': 'failure', 'updated_at': '2000-01-01T00:00:00Z'}
    def get(url):
        value = {'workflow_runs': [run]} if url == mirror.WORKFLOW else {}
        return SimpleNamespace(json=lambda: value, text='public')
    monkeypatch.setattr(mirror, '_get', get)
    monkeypatch.setattr(mirror, '_notify', lambda *a, **k: events.append(a))
    mirror.refresh()
    assert mirror.view('owner')['status'] == 'OUTDATED'
    assert not any(a[1] == 'MIRROR_SYNC_FAILED' for a in events)
    run['updated_at'] = '2099-01-01T00:00:00Z'
    mirror.refresh()
    assert mirror.view('owner')['status'] == 'ERROR'
    assert mirror.view('owner')['primary_status'] == 'PRIMARY_PUBLISHED'
    assert any(a[1] == 'MIRROR_SYNC_FAILED' for a in events)


def test_private_host_cannot_expose_public_manifest(editorial):
    app = Flask(__name__)
    with app.test_request_context('/mirror-manifest.json', base_url='https://www.reposnews.com'):
        response = rn.public_dispatch()
        assert response.status_code == 200 and 'owner' not in response.get_data(as_text=True)
    with app.test_request_context('/mirror-manifest.json', base_url='https://private.example'):
        assert rn.public_dispatch() is None


def test_runner_skips_unchanged_verified_public_content(editorial):
    source = mirror.public_manifest()
    current = source | {'mirror_policy': 'noindex,follow', 'last_static_build': datetime.now(timezone.utc).isoformat()}
    assert runner.unchanged(source, current)
    assert not runner.unchanged(source, current | {'request_nonce': 'new-manual-request'})
    assert not runner.unchanged(source, current | {'last_static_build': '2000-01-01T00:00:00+00:00'})


def test_native_notifications_deduplicate_and_resolve_failure(editorial):
    from app import holdings, identity_center
    mirror._notify('owner', 'MIRROR_SYNC_FAILED', 'test-mirror-failed', 'Mirror pendiente', 'Primary remains published', True)
    mirror._notify('owner', 'MIRROR_SYNC_SUCCESS', 'test-mirror-success', 'Mirror actualizado', '1 artículo')
    mirror._notify('owner', 'MIRROR_SYNC_SUCCESS', 'test-mirror-success', 'Mirror actualizado', '1 artículo')
    rows = identity_center.ensure(holdings.read('owner'))['human_actions']
    failed = next(r for r in rows if r.get('notification_key') == 'test-mirror-failed')
    assert failed['status'] == 'COMPLETED'
    assert [a['label'] for a in failed['actions']] == ['VER MIRROR', 'VER PRODUCCIÓN']
    assert len([r for r in rows if r.get('notification_key') == 'test-mirror-success']) == 1
