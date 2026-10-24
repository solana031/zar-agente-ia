import importlib.util
import json
from pathlib import Path
import pytest
from contextlib import nullcontext
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('static_host', Path(__file__).parents[1]/'tools/reposnews_static_host.py')
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


@pytest.fixture
def artifact(tmp_path):
    (tmp_path/'build-manifest.json').write_text(json.dumps({'status': 'STATIC_HOST_READY', 'backend_required': False}))
    (tmp_path/'index.html').write_text('approved public content')
    return tmp_path


def test_deploy_requires_exact_reviewed_artifact(artifact, monkeypatch):
    digest = host.artifact_digest(artifact)
    (artifact/'index.html').write_text('changed')
    monkeypatch.setattr(host.subprocess, 'check_output', lambda *a, **k: pytest.fail('must not deploy'))
    with pytest.raises(ValueError, match='APPROVED_ARTIFACT_CHANGED'):
        host.deploy(artifact, digest, artifact/'checkout')


def test_private_files_never_deploy(artifact):
    (artifact/'token.json').write_text('private')
    with pytest.raises(ValueError, match='NONPUBLIC'):
        host.artifact_digest(artifact)


def test_verification_rejects_backend_redirect(artifact, monkeypatch):
    response = SimpleNamespace(status=200, url='https://web-production-a9565.up.railway.app/', read=lambda: b'')
    monkeypatch.setattr(host, 'urlopen', lambda *a, **k: nullcontext(response))
    with pytest.raises(ValueError, match='STATIC_HTTP_OR_CONTENT_MISMATCH'):
        host.verify(artifact)


def test_unrelated_deploy_host_is_rejected(artifact):
    with pytest.raises(ValueError, match='PUBLIC_HOST_REQUIRED'):
        host.deploy(artifact, 'unused', artifact/'checkout', public_base='https://unrelated.example')


def test_rollback_config_is_readonly_and_preserves_current_records():
    snapshot = {'records': [{'Name': 'www.reposnews.com', 'Type': 'CNAME', 'NameHost': '4a4tnij4.up.railway.app'}]}
    plan = host.cutover_plan(snapshot)
    assert plan['current_dns'] == snapshot
    assert plan['dns_changed'] is False and plan['approval_required'] is True
    assert plan['canonical'] == 'https://www.reposnews.com'
    assert plan['target_dns'][0]['values'] == ['solana031.github.io']
    assert len(plan['target_dns'][1]['values']) == len(plan['target_dns'][2]['values']) == 4


def test_static_https_verification(artifact, monkeypatch):
    class Response:
        status = 200
        url = host.PREVIEW
        def __init__(self, data): self.data = data
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return self.data
    def fetch(url, **kwargs):
        assert url.startswith(host.PREVIEW)
        return Response((artifact/('build-manifest.json' if url.endswith('.json') else 'index.html')).read_bytes())
    monkeypatch.setattr(host, 'urlopen', fetch)
    assert host.verify(artifact)['checked'] == 2


@pytest.fixture
def publication(monkeypatch):
    from app import reposnews_static_publish as pipeline
    from app.reposnews_automation import revision
    article = {'image_asset':'fastapi-official.png', 'id': 'approved', 'state': 'PUBLISHED', 'published': True, 'title_es': 'Public article', 'approval_status': 'APPROVED_BY_USER'}
    article['approval'] = {'owner': 'owner', 'revision': revision(article), 'at': '2026-10-19'}
    monkeypatch.setattr(pipeline.rn, 'read', lambda: {'owner': 'owner', 'articles': [article]})
    events = []
    monkeypatch.setattr(pipeline, 'emit', lambda *a, **k: events.append((a, k)))
    return pipeline, article, events


def test_publication_gate_blocks_before_build(publication):
    pipeline, article, events = publication
    article['approval_status'] = 'PENDING'
    with pytest.raises(ValueError, match='EXPLICIT_USER_APPROVAL'):
        pipeline.publish_approved('owner', 'approved', build=lambda: pytest.fail('unapproved build'), deploy=None, verify=None)
    assert not events


def test_publication_verifies_before_success_notification(publication):
    pipeline, article, events = publication
    calls = []
    def build(): calls.append('build'); return 'artifact'
    def deploy(artifact): calls.append('deploy'); return {'url': host.PREVIEW, 'commit': 'abc'}
    def verify(*args): calls.append('verify'); return {'ok': True}
    pipeline.publish_approved('owner', 'approved', build=build, deploy=deploy, verify=verify)
    assert calls == ['build', 'deploy', 'verify']
    assert events[0][0][1] == 'PUBLISH_SUCCESS'
    assert events[0][1]['status'] == 'COMPLETED'


def test_deploy_failure_keeps_editorial_revision_and_notifies(publication):
    pipeline, article, events = publication
    before = json.dumps(article, sort_keys=True)
    def fail(artifact): raise RuntimeError('provider unavailable')
    with pytest.raises(RuntimeError):
        pipeline.publish_approved('owner', 'approved', build=lambda: 'artifact', deploy=fail, verify=lambda *args: pytest.fail('no verify after failure'))
    assert json.dumps(article, sort_keys=True) == before
    assert events[0][0][1] == 'PUBLISH_FAILED'
    assert [action['label'] for action in events[0][0][8]] == ['RETRY', 'DETAILS']
