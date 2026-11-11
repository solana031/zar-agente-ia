import hashlib
import io
import time

import pytest
from PIL import Image
from app import reposnews as rn, reposnews_cover_art as art, instagram_local_queue as local_queue
from app.reposnews_assets import public_article
from app.reposnews_cover_providers import editorial, INTERNAL


def article(slug, summary):
    return {'id': slug, 'repo': 'owner/' + slug, 'category': 'Developer Tools', 'title_es': slug.title(),
            'summary_es': summary, 'title_en': slug.title(), 'summary_en': summary}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv('ZAR_DATA_DIR', str(tmp_path))
    rn.write({'owner': 'fixture-owner', 'articles': [], 'instagram_inbox': []})
    return rn.read


def test_each_article_gets_a_distinct_readable_cover():
    a = article('voice-tool', 'Clona voces y dobla vídeos en local.')
    b = article('trade-bot', 'Agentes que operan en mercados con paper trading.')
    first, second = art.render(a), art.render(b)
    assert hashlib.sha256(first).digest() != hashlib.sha256(second).digest()
    with Image.open(io.BytesIO(first)) as image:
        assert image.size == (1280, 720)
    assert art.heuristic_spec(a)['hero'] == 'voice' and art.heuristic_spec(b)['hero'] == 'trade'


def test_ai_spec_is_sanitized_to_known_icons_and_short_labels():
    spec = art.sanitize_spec({'name': 'X' * 80, 'tagline': 'Hace algo https://evil.example útil', 'hero': 'not-an-icon',
                              'steps': [{'icon': 'video', 'label': 'Entrada de vídeo larga'}, {'icon': 'ai', 'label': 'IA'},
                                        {'icon': 'bogus', 'label': 'x'}, {'icon': 'web', 'label': 'Web'}]},
                             article('demo', 'Herramienta de vídeo'))
    assert len(spec['name']) <= 34 and 'http' not in spec['tagline']
    assert spec['hero'] in art.ICONS and [s['icon'] for s in spec['steps']] == ['video', 'ai', 'web']
    assert all(len(s['label']) <= 18 for s in spec['steps'])


def test_curated_specs_cover_existing_generic_articles():
    spec = art.spec_for(article('hkuds-ai-trader', ''))
    assert spec['source'] == 'CURATED' and spec['name'] == 'AI-Trader' and not art.needs_spec(article('hkuds-ai-trader', ''))


def test_legacy_generic_canvas_is_replaced_publicly():
    legacy = dict(article('demo', 'x'), image_asset='cover-' + 'a' * 24 + '.png',
                  cover_provenance={'source_type': 'GENERATED', 'generator': 'ReposNews/internal-editorial-canvas-v1'})
    shown = public_article(legacy)
    assert shown['cover_url'] == '/media/reposnews/editorial-demo.png'
    official = dict(legacy, cover_provenance={'source_type': 'OFFICIAL'})
    assert public_article(official)['image_asset'] == legacy['image_asset']


def test_editorial_fallback_uses_ai_spec_when_available(monkeypatch):
    monkeypatch.setattr(art, 'generate_spec', lambda a, analysis=None: art.sanitize_spec(
        {'name': 'Demo', 'tagline': 'Demo', 'hero': 'game', 'steps': [{'icon': 'chat', 'label': 'A'}, {'icon': 'ai', 'label': 'B'}, {'icon': 'game', 'label': 'C'}]}, a))
    item = article('new-project', 'Juegos con IA')
    blob, provider = editorial(item, {'video_summary': 'demo'})
    assert provider == INTERNAL == art.GENERATOR and item['cover_spec']['hero'] == 'game' and blob.startswith(b'\x89PNG')


def test_editorial_fallback_survives_provider_failure(monkeypatch):
    def fail(*a, **k):
        raise ValueError('PROVIDER_DOWN')
    monkeypatch.setattr(art, 'generate_spec', fail)
    item = article('offline-project', 'Panel de datos en tiempo real')
    blob, _ = editorial(item)
    assert blob.startswith(b'\x89PNG') and 'cover_spec' not in item


def test_spec_tick_stores_spec_on_published_snapshot(store, monkeypatch):
    published = dict(article('fresh-tool', 'Automatiza vídeos'), state='PUBLISHED', published=True)
    published['published_snapshot'] = dict(published)
    data = store(); data['articles'] = [published]
    data['instagram_inbox'] = [{'id': 'row', 'article_id': 'fresh-tool', 'analysis': {'video_summary': 'Explica el flujo'}}]
    rn.write(data)
    seen = {}

    def fake(subject, analysis=None):
        seen['analysis'] = analysis
        return art.sanitize_spec({'name': 'Fresh', 'tagline': 't', 'hero': 'video',
                                  'steps': [{'icon': 'text', 'label': 'a'}, {'icon': 'ai', 'label': 'b'}, {'icon': 'video', 'label': 'c'}]}, subject)
    monkeypatch.setattr(art, 'generate_spec', fake)
    assert art.tick()['name'] == 'Fresh'
    stored = store()['articles'][0]
    assert stored['published_snapshot']['cover_spec']['name'] == 'Fresh' and seen['analysis']['video_summary']
    assert art.tick() is None  # Nothing left to do.


def test_offline_local_worker_does_not_block_reels(store):
    now = time.time()
    data = store()
    data['instagram_inbox'] = [{'id': 'r1', 'status': 'WAITING_LOCAL_WORKER', 'attempts': 0},
                               {'id': 'r2', 'status': 'WAITING_LOCAL_WORKER', 'attempts': 0, 'local_lease': now + 5000}]
    rn.write(data)
    assert local_queue.fallback_stalled(now) == 0
    assert local_queue.fallback_stalled(now + local_queue.LOCAL_GRACE + 1) == 1
    rows = {r['id']: r for r in store()['instagram_inbox']}
    assert rows['r1']['status'] == 'RECEIVED' and rows['r1']['local_fallback'] is True
    assert rows['r2']['status'] == 'WAITING_LOCAL_WORKER'


def test_online_local_worker_keeps_its_queue(store):
    now = time.time()
    data = store(); data['instagram_local_worker'] = {'seen': now}
    data['instagram_inbox'] = [{'id': 'r1', 'status': 'WAITING_LOCAL_WORKER', 'local_waiting_since': now - 10 * local_queue.LOCAL_GRACE}]
    rn.write(data)
    assert local_queue.fallback_stalled(now) == 0
