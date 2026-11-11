import pytest
from app import reposnews as rn, reposnews_enrich as enrich, holdings


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv('ZAR_DATA_DIR', str(tmp_path))
    article = {'id': 'tool', 'repo': 'owner/tool', 'repository_url': 'https://github.com/owner/tool', 'published': True, 'state': 'PUBLISHED',
               'title_es': 'T', 'title_en': 'T', 'summary_es': 's', 'summary_en': 's', 'body_es': 'palabra ' * 300, 'body_en': 'word ' * 300,
               'image_asset': 'cover-' + 'a' * 24 + '.png', 'seo': {'es': {'canonical': 'x'}, 'en': {'canonical': 'y'}}, 'sources': ['a', 'b']}
    article['published_snapshot'] = dict(article)
    rn.write({'owner': 's_owner', 'articles': [article], 'article_revisions': []})
    return rn.read


def test_short_published_guides_become_private_update_proposals(store, monkeypatch):
    from app import reposnews_inbox as inbox
    monkeypatch.setattr(inbox, 'research', lambda repo: {'repo': repo})
    monkeypatch.setattr(inbox, 'build', lambda package, discovery: {'id': 'other', 'title_es': 'T2', 'title_en': 'T2', 'summary_es': 's', 'summary_en': 's',
                        'body_es': 'palabra ' * 900, 'body_en': 'word ' * 900, 'image_asset': 'new.png', 'seo': {}})
    enrich._last = 0
    ident = enrich.tick()
    data = store()
    revision = data['article_revisions'][0]
    assert revision['article_revision_id'] == ident and revision['kind'] == 'ENRICHMENT'
    assert revision['draft']['id'] == 'tool' and revision['draft']['image_asset'] == 'cover-' + 'a' * 24 + '.png'
    assert revision['draft']['seo'] == {'es': {'canonical': 'x'}, 'en': {'canonical': 'y'}}
    assert '300 → 900' in revision['change_summary'] and not data['articles'][0]['body_es'].startswith('palabra ' * 900)
    assert enrich.status(data)['pending'] == 1
    enrich._last = 0
    assert enrich.tick() is None  # already pending: no duplicate proposal


def test_failed_expansion_is_retried_later_not_published(store, monkeypatch):
    from app import reposnews_inbox as inbox
    monkeypatch.setattr(inbox, 'research', lambda repo: (_ for _ in ()).throw(ValueError('OFFICIAL_REPOSITORY_REQUIRED')))
    enrich._last = 0
    assert enrich.tick() is None
    article = store()['articles'][0]
    assert article['enrich_job']['error'] == 'OFFICIAL_REPOSITORY_REQUIRED' and not store()['article_revisions']
