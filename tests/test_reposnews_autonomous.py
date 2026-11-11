from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest
from flask import Flask, session
from app import reposnews as rn, reposnews_autonomous as scheduled, reposnews_automation as automation


NOW = datetime(2026, 10, 28, 17, 0, tzinfo=timezone.utc)  # 18:00 Madrid


def candidate(index):
    return {'repo': f'owner/tool{index}', 'monthly_stars': 100, 'rank': index + 1,
            'source': scheduled.TRENDING, 'observed_at': NOW.isoformat()}


def draft(item):
    a = {'id': item['repo'].replace('/', '-'), 'repo': item['repo'], 'state': 'READY_PRIVATE',
         'published': False, 'sources': ['https://github.com/' + item['repo'], 'https://github.com/' + item['repo'] + '/releases'],
         'image_asset': 'fastapi-official.png', 'review_kind': 'AUTOMATED_SOURCE_REVIEW',
         'review': {'supported': True, 'commands_supported': True, 'privacy_safe': True}, 'monthly_trend': item}
    for lang in ('es', 'en'):
        a.update({'title_' + lang: 'Verified guide', 'summary_' + lang: 'Source-backed summary', 'body_' + lang: 'verified fact ' * 260})
    return rn.article_defaults(a)


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv('ZAR_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(scheduled, 'utcnow', lambda: NOW)
    monkeypatch.setattr(rn, 'legal_status', lambda data: {'status': 'LEGAL_READY'})
    monkeypatch.setattr('app.jev_decision.proposal', lambda *a, **k: {'id': 'fixture', 'decision': 'ALLOW'})
    monkeypatch.setattr('app.jev_decision.decision_state', lambda *a, **k: None)
    monkeypatch.setattr(scheduled, 'monthly_candidates', lambda: [candidate(i) for i in range(12)])
    monkeypatch.setattr(scheduled, 'prepare', draft)
    rn.write({'owner': 'fixture-owner', 'articles': [], 'autonomous_editorial': {
        'enabled': True, 'owner': 'fixture-owner', 'grant': 'fixture-grant', 'first_slot': NOW.isoformat()}})
    return rn.read


@pytest.mark.parametrize('date,expected', [
    ('2026-10-23T16:00:00+00:00', '2026-10-26T18:00:00+01:00'),
    ('2026-10-28T16:59:00+00:00', '2026-10-28T18:00:00+01:00'),
    ('2027-03-26T17:00:00+00:00', '2027-03-29T18:00:00+02:00'),
])
def test_local_schedule_and_dst(date, expected):
    assert scheduled.next_slot(datetime.fromisoformat(date)).isoformat() == expected


@pytest.mark.parametrize('date', ['2026-10-28T16:59:00+00:00', '2026-10-31T17:00:00+00:00'])
def test_not_before_hour_or_weekends(state, date):
    scheduled.tick(datetime.fromisoformat(date))
    assert not state().get('autonomous_editorial_jobs')


def test_default_disabled_never_fetches(state, monkeypatch):
    data = state(); data.pop('autonomous_editorial'); rn.write(data)
    monkeypatch.setattr(scheduled, 'monthly_candidates', lambda: pytest.fail('network while disabled'))
    scheduled.tick()
    assert state()['articles'] == []


def test_four_publications_and_repeat_ticks_are_idempotent(state):
    scheduled.tick(); scheduled.tick()
    data = state()
    assert len(data['articles']) == 4
    assert all(a['published'] and a['published_snapshot']['body_en'] for a in data['articles'])
    assert data['autonomous_editorial_jobs']['2026-10-28']['status'] == 'COMPLETED'
    assert all(a['approval_status'] == 'OWNER_AUTHORIZED_SCHEDULE' for a in data['articles'])
    assert 'OWNER_AUTHORIZED_AUTONOMOUS_EDITORIAL' in data['articles'][0]['history'][-1]['reason']


def test_daily_policy_fills_six_on_weekend_counting_only_published(state, monkeypatch):
    saturday = datetime(2026, 10, 31, 17, tzinfo=timezone.utc)
    monkeypatch.setattr(scheduled, 'utcnow', lambda: saturday)
    monkeypatch.setattr(scheduled.holdings, '_now', lambda: saturday.isoformat())
    monkeypatch.setattr(scheduled, 'monthly_candidates', lambda: [
        dict(candidate(i), observed_at=saturday.isoformat()) for i in range(12)])
    data = state()
    data['autonomous_editorial']['purpose'] = 'DAILY_GUIDES_AND_INBOUND_REELS'
    data['articles'] = [dict(draft(candidate(90)), published=True, published_at=saturday.isoformat()), draft(candidate(91))]
    data['instagram_inbox'] = [{'received_at': saturday.isoformat(), 'article_id': data['articles'][1]['id']}]
    rn.write(data)
    scheduled.tick(); scheduled.tick()
    assert len(scheduled.published_today(state(), saturday)) == 6
    assert len(state()['autonomous_editorial_jobs']['2026-10-31']['published']) == 5


def test_ready_reels_publish_only_with_current_ingress_grant(state, monkeypatch):
    monkeypatch.setattr('app.reposnews_inbox.sender_ids', lambda: {'fixture-sender'})
    data = state()
    data['autonomous_editorial']['purpose'] = 'DAILY_GUIDES_AND_INBOUND_REELS'
    for i in range(4):
        row = {'id': str(i), 'external_id': str(i), 'received_at': f'2026-10-28T0{i}:00:00Z',
               'source_url': f'https://www.instagram.com/reel/fixture{i}/', 'sender': 'fixture-sender',
               'status': 'READY_PRIVATE', 'auto_publish_grant': 'fixture-grant'}
        article = draft(candidate(i))
        article['inbox_item_id'] = row['id']
        row['article_id'] = article['id']
        if i == 1: row['backfill'] = True
        if i == 2: row['auto_publish_grant'] = 'previous-grant'
        if i == 3: row['sender'] = 'unknown'
        data.setdefault('instagram_inbox', []).append(row)
        data['articles'].append(article)
    rn.write(data)
    scheduled.publish_ready_reels(); scheduled.publish_ready_reels()
    # Historical Reels from the authorized conversation are covered by the owner policy.
    assert [a['id'] for a in state()['articles'] if a['published']] == ['owner-tool0', 'owner-tool1']
    assert state()['instagram_inbox'][0]['status'] == 'PUBLISHED'


def test_historical_reels_are_paced_and_respect_owner_hold(state, monkeypatch):
    monkeypatch.setattr('app.reposnews_inbox.sender_ids', lambda: {'fixture-sender'})
    data = state()
    data['autonomous_editorial']['purpose'] = 'DAILY_GUIDES_AND_INBOUND_REELS'
    for i in range(3):
        row = {'id': str(i), 'external_id': str(i), 'received_at': f'2026-10-28T0{i}:00:00Z', 'backfill': True,
               'source_url': f'https://www.instagram.com/reel/fixture{i}/', 'sender': 'fixture-sender',
               'status': 'READY_PRIVATE'}
        if i == 2: row['auto_publish_owner_hold'] = True
        article = draft(candidate(i))
        article['inbox_item_id'] = row['id']
        row['article_id'] = article['id']
        data.setdefault('instagram_inbox', []).append(row)
        data['articles'].append(article)
    rn.write(data)
    scheduled.publish_ready_reels(); scheduled.publish_ready_reels()
    # Drafts without a grant receive the current one; only one historical article per spacing window.
    assert [a['id'] for a in state()['articles'] if a['published']] == ['owner-tool0']
    data = state(); data['autonomous_reel_pacing']['last_backfill_publish'] -= scheduled.BACKFILL_SPACING + 1; rn.write(data)
    scheduled.publish_ready_reels()
    assert [a['id'] for a in state()['articles'] if a['published']] == ['owner-tool0', 'owner-tool1']
    data = state(); data['autonomous_reel_pacing']['last_backfill_publish'] -= scheduled.BACKFILL_SPACING + 1; rn.write(data)
    scheduled.publish_ready_reels()
    assert not state()['articles'][2]['published'] and 'auto_publish_grant' not in state()['instagram_inbox'][2]


def test_authorized_backlog_publishes_only_the_current_finite_set(state, monkeypatch):
    from app import reposnews_history as history
    monkeypatch.setattr('app.reposnews_inbox.sender_ids', lambda: {'fixture-sender'})
    monkeypatch.setattr('app.reposnews_inbox.start_worker', lambda: None)
    monkeypatch.setattr(rn, 'state', lambda scope: rn.read())
    data = state()
    data['autonomous_editorial']['enabled'] = False
    article = draft(candidate(0))
    article['inbox_item_id'] = 'old-reel'
    row = {'id': 'old-reel', 'article_id': article['id'], 'status': 'READY_PRIVATE',
           'sender': 'fixture-sender', 'external_id': 'old', 'backfill': True,
           'source_url': 'https://www.instagram.com/reel/existing/'}
    data.update(articles=[article], instagram_inbox=[row])
    rn.write(data)
    with pytest.raises(ValueError, match='AUTHENTICATED_OWNER_REQUIRED'):
        history.start('fixture-owner', authorize_publication=True)
    app = Flask(__name__); app.secret_key = 'TEST'
    with app.test_request_context():
        session['zar_auth'] = True
        history.start('fixture-owner', authorize_publication=True)
    data = state()
    assert data['backlog_publication']['item_ids'] == ['old-reel']
    future = draft(candidate(1)); future['inbox_item_id'] = 'future-reel'
    data['articles'].append(future)
    data['instagram_inbox'].append(dict(row, id='future-reel', article_id=future['id'], external_id='future',
                                       source_url='https://www.instagram.com/reel/future/'))
    rn.write(data)
    scheduled.publish_ready_reels(); scheduled.publish_ready_reels()
    assert [a['id'] for a in state()['articles'] if a.get('published')] == [article['id']]


@pytest.mark.parametrize('status', ['NEEDS_DISAMBIGUATION', 'FAILED_SOURCE', 'FAILED_PERMANENT'])
def test_owner_can_clarify_an_exact_repository_without_broad_name_search(state, monkeypatch, status):
    monkeypatch.setattr(rn, 'state', lambda scope: rn.read())
    data = state(); item = 'a' * 24
    data['instagram_inbox'] = [{'id': item, 'status': status}]
    rn.write(data)
    rn.operate('fixture-owner', 'inbox_resolve', {'id': item, 'name': 'https://github.com/moorcheh-ai/memanto'})
    row = state()['instagram_inbox'][0]
    assert row['clarified_repository'] == 'moorcheh-ai/memanto'
    assert row['clarified_project'] == 'memanto' and row['status'] == 'RECEIVED'


def test_today_new_reel_article_skips_fallback(state):
    data = state(); article = draft(candidate(99)); data['articles'].append(article)
    data['instagram_inbox'] = [{'received_at': NOW.isoformat(), 'article_id': article['id']}]
    rn.write(data); scheduled.tick()
    assert len(state()['articles']) == 1
    assert state()['autonomous_editorial_jobs']['2026-10-28']['status'] == 'SKIPPED_REELS'


@pytest.mark.parametrize('extra', [{'backfill': True}, {'received_at': '2026-10-27T12:00:00Z'}])
def test_backfill_and_yesterday_do_not_suppress_today(state, extra):
    data = state(); article = draft(candidate(99)); data['articles'].append(article)
    data['instagram_inbox'] = [dict({'received_at': NOW.isoformat(), 'article_id': article['id']}, **extra)]
    rn.write(data); scheduled.tick()
    assert len(state()['articles']) == 5


def test_dedup_includes_existing_private_drafts(state):
    data = state(); data['articles'] = [draft(candidate(0))]; rn.write(data)
    scheduled.tick()
    repos = [a['repo'] for a in state()['articles']]
    assert len(repos) == len(set(repos)) == 5


def test_reel_arriving_during_generation_stops_publication(state, monkeypatch):
    def arriving(item):
        data = state(); reel = draft(candidate(99)); data['articles'].append(reel)
        data['instagram_inbox'] = [{'received_at': NOW.isoformat(), 'article_id': reel['id']}]
        rn.write(data)
        return draft(item)
    monkeypatch.setattr(scheduled, 'prepare', arriving)
    scheduled.tick()
    assert not any(a['published'] for a in state()['articles'])


def test_global_stop_and_legal_block(state, monkeypatch):
    from app import holdings
    monkeypatch.setattr(holdings, 'read', lambda scope: {'global_stop': True})
    scheduled.tick(); assert not state()['articles']
    monkeypatch.setattr(holdings, 'read', lambda scope: {})
    monkeypatch.setattr(rn, 'legal_status', lambda data: {'status': 'LEGAL_PENDING'})
    scheduled.tick(); assert not state()['articles']


def test_failed_quality_is_not_published(state, monkeypatch):
    monkeypatch.setattr(scheduled, 'prepare', lambda row: (_ for _ in ()).throw(ValueError('EDITORIAL_REVIEW_REQUIRED')))
    scheduled.tick()
    data = state()
    assert not data['articles']
    assert len(data['autonomous_editorial_jobs']['2026-10-28']['tried']) == 8


def test_active_lease_prevents_second_worker(state, monkeypatch):
    data = state(); data['autonomous_editorial_jobs'] = {'2026-10-28': {
        'attempts': 1, 'status': 'RUNNING', 'lease_until': NOW.timestamp() + 100}}
    rn.write(data)
    monkeypatch.setattr(scheduled, 'monthly_candidates', lambda: pytest.fail('parallel job'))
    scheduled.tick()


def test_source_failure_backoff_and_retry_limit(state, monkeypatch):
    calls = []
    def unavailable():
        calls.append(1)
        raise ValueError('MONTHLY_SOURCE_UNAVAILABLE')
    monkeypatch.setattr(scheduled, 'monthly_candidates', unavailable)
    monkeypatch.setattr(scheduled.time, 'time', lambda: NOW.timestamp())
    scheduled.tick(); scheduled.tick()
    assert len(calls) == 1
    data = state(); data['autonomous_editorial_jobs']['2026-10-28']['retry_after'] = 0; rn.write(data)
    scheduled.tick(); scheduled.tick()
    assert len(calls) == 2
    assert not state()['articles']


def test_pause_during_generation_blocks_publication(state, monkeypatch):
    def paused(item):
        data = state(); data['autonomous_editorial']['enabled'] = False; rn.write(data)
        return draft(item)
    monkeypatch.setattr(scheduled, 'prepare', paused)
    scheduled.tick()
    assert not state()['articles']


def test_unverified_review_and_invalid_cover_fail_closed(state, monkeypatch):
    def unsupported(item):
        article = draft(item); article['review']['supported'] = False
        return article
    monkeypatch.setattr(scheduled, 'prepare', unsupported)
    scheduled.tick(); assert not state()['articles']
    data = state(); data.pop('autonomous_editorial_jobs'); rn.write(data)
    monkeypatch.setattr(scheduled, 'prepare', draft)
    monkeypatch.setattr('app.reposnews_covers.valid', lambda article: False)
    scheduled.tick(); assert not state()['articles']


def test_expired_lease_resumes_without_duplicate_publication(state):
    data = state(); data['articles'] = [dict(draft(candidate(0)), published=True)]
    data['autonomous_editorial_jobs'] = {'2026-10-28': {'day': '2026-10-28', 'attempts': 1,
        'status': 'RUNNING', 'lease_until': 0, 'published': ['owner-tool0'], 'tried': ['owner/tool0'], 'prepared': {}}}
    rn.write(data); scheduled.tick()
    assert len(state()['articles']) == 4


def test_forged_schedule_marker_does_not_bypass_manual_gate(state):
    article = draft(candidate(0)); article['approval_status'] = 'OWNER_AUTHORIZED_SCHEDULE'
    article['autonomous_authorization'] = {'day': '2026-10-28', 'grant': 'fixture-grant'}
    with pytest.raises(ValueError, match='EXPLICIT_USER_APPROVAL_REQUIRED'):
        automation.gate(article, 'fixture-owner')


def test_revision_change_revocation_and_daily_cap_reject(state):
    article = draft(candidate(0)); article.update(approval_status='OWNER_AUTHORIZED_SCHEDULE',
        autonomous_authorization={'day': '2026-10-28', 'grant': 'fixture-grant'})
    data = state(); data['autonomous_editorial_jobs'] = {'2026-10-28': {
        'status': 'RUNNING', 'grant': 'fixture-grant', 'lease_until': NOW.timestamp() + 10,
        'prepared': {article['id']: {'repo': article['repo'], 'revision': automation.revision(article)}}}}
    assert scheduled.authorized(article, 'fixture-owner', data)
    changed = deepcopy(article); changed['body_es'] += ' changed'
    assert not scheduled.authorized(changed, 'fixture-owner', data)
    assert not scheduled.authorized(article, 'other-owner', data)
    data['autonomous_editorial_jobs']['2026-10-28']['published'] = ['a', 'b', 'c', 'd']
    assert not scheduled.authorized(article, 'fixture-owner', data)
    data['autonomous_editorial']['enabled'] = False
    assert not scheduled.authorized(article, 'fixture-owner', data)


def test_policy_requires_authenticated_explicit_authorization(state, monkeypatch):
    app = Flask(__name__); app.secret_key = 'fixture'
    monkeypatch.setattr(rn, 'state', lambda scope: rn.read())
    with app.test_request_context():
        with pytest.raises(ValueError, match='AUTHENTICATED_OWNER_REQUIRED'):
            scheduled.configure('fixture-owner', {'enabled': True, 'authorize_publication': True})
        session['zar_auth'] = True
        with pytest.raises(ValueError, match='AUTHORIZATION_REQUIRED'):
            scheduled.configure('fixture-owner', {'enabled': True})
        scheduled.configure('fixture-owner', {'enabled': False})
        assert not state()['autonomous_editorial']['enabled']
        scheduled.configure('fixture-owner', {'enabled': True, 'authorize_publication': True})
        assert state()['autonomous_editorial']['first_slot'] == '2026-10-29T18:00:00+01:00'


def test_monthly_parser_requires_measured_monthly_growth():
    parser = scheduled.MonthlyParser()
    parser.feed('<article class="Box-row"><h2><a href="/a/b">A / B</a></h2>25,000 total stars <span>1,234 stars this month</span></article>'
                '<article class="Box-row"><h2><a href="/x/y">X / Y</a></h2>999,999 total stars</article>')
    assert parser.rows == [{'repo': 'a/b', 'monthly_stars': 1234}]


def test_monthly_live_fixture_if_available():
    path = Path('.local/trending-monthly-fixture.html')
    if not path.exists():
        pytest.skip('optional recorded official HTML not present')
    parser = scheduled.MonthlyParser(); parser.feed(path.read_text(encoding='utf8'))
    assert len(parser.rows) >= 3
    assert all(row['monthly_stars'] > 0 for row in parser.rows)
