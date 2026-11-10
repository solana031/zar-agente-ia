"""Read-only provider calls, owner boundaries and stale-cache behavior, entirely offline."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from flask import Flask
from google.oauth2.credentials import Credentials

from app import business_workflows, cloud_auth, google_accounts, holdings, reposnews as rn
from app import reposnews_metrics as metrics


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv('ZAR_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(cloud_auth, 'DATA_DIR', tmp_path)
    rn.write({'owner': 'owner', 'articles': [], 'publisher': 'pub-1234567890123456'})
    return tmp_path


def traffic(clicks=17, impressions=2080):
    return {'clicks': clicks, 'impressions': impressions, 'ctr': clicks / impressions,
            'position': 8.4}


def token():
    return SimpleNamespace(token='TEST-private', scopes=list(metrics.SERVICES.values()))


def response(data, status=200):
    return Mock(ok=status < 300, status_code=status, json=lambda: data)


def test_search_totals_dates_provisional_and_page_aggregation(store):
    now = datetime(2026, 11, 11, 0, 30, tzinfo=timezone.utc)
    replies = [
        response({'rows': [traffic()]}),
        response({'rows': [dict(keys=['2026-11-10'], **traffic())],
                  'metadata': {'first_incomplete_date': '2026-11-10'}}),
        response({'rows': [traffic(2, 100)]}),
        response({'rows': [dict(keys=['https://www.reposnews.com/es/repositorios/tool/'], **traffic())]}),
    ]
    with patch.object(metrics.requests, 'post', side_effect=replies) as post:
        result = metrics.search_console(token(), now)
    assert result['end_date'] == '2026-11-10'  # Google's Pacific date, not Madrid's.
    assert result['start_date'] == '2026-10-14'
    assert result['totals']['clicks'] == 17
    assert result['previous']['clicks'] == 2
    assert result['first_incomplete_date'] == '2026-11-10'
    assert result['latest_date'] == '2026-11-10'
    assert post.call_args_list[0].kwargs['json']['aggregationType'] == 'byProperty'
    assert post.call_args_list[-1].kwargs['json']['aggregationType'] == 'byPage'
    assert post.call_args_list[-1].kwargs['json']['rowLimit'] == 10
    assert post.call_args_list[2].kwargs['json']['endDate'] == '2026-10-13'
    assert 'sc-domain%3Areposnews.com' in post.call_args.args[0]
    assert post.call_args.kwargs['allow_redirects'] is False


def test_no_rows_and_permission_error_have_distinct_states(store):
    with patch.object(metrics.requests, 'post', return_value=response({})):
        result = metrics.search_console(token())
    assert result['empty'] and result['totals'] is None and result['daily'] == []
    with patch.object(metrics.requests, 'post', return_value=response({}, 403)):
        with pytest.raises(metrics.MetricsError, match='NEEDS_PERMISSION'):
            metrics.search_console(token())


def test_adsense_only_reads_approval_and_matches_configured_publisher(store):
    replies = [
        response({'accounts': [{'name': 'accounts/pub-1234567890123456', 'state': 'READY'}]}),
        response({'sites': [{'domain': 'reposnews.com', 'state': 'NEEDS_ATTENTION', 'autoAdsEnabled': False}]}),
    ]
    with patch('app.adsense_adapter.requests.Session.get', side_effect=replies) as get:
        result = metrics.adsense(token(), rn.read())
    assert result['account_state'] == 'READY'
    assert result['site_state'] == 'NEEDS_ATTENTION'
    assert result['auto_ads_enabled'] is False
    assert get.call_count == 2
    assert all('reports' not in call.args[0] and 'payments' not in call.args[0] for call in get.call_args_list)
    assert get.call_args.kwargs['headers']['Authorization'] == 'Bearer TEST-private'


def test_adsense_does_not_guess_an_account_or_a_site_approval(store):
    with patch.object(metrics.AdSenseAdapter, 'accounts', return_value=[]):
        assert metrics.adsense(token(), rn.read())['site_state'] == 'NOT_ADDED'
    with patch.object(metrics.AdSenseAdapter, 'accounts', return_value=[{'name': 'accounts/pub-other'}]):
        with pytest.raises(metrics.MetricsError, match='PUBLISHER_MISMATCH'):
            metrics.adsense(token(), rn.read())


def test_cache_avoids_repeated_reads_and_preserves_success_on_outage(store):
    with patch.object(metrics, '_credentials', return_value=token()), patch.object(
            metrics, 'search_console', return_value={'totals': traffic()}) as provider:
        result = metrics.refresh('owner', {'provider': 'search_console'})
        metrics.refresh('owner', {'provider': 'search_console', 'refresh': True})
    assert provider.call_count == 1
    checked = result['providers']['search_console']['checked_at']
    data = holdings.read('owner')
    data['reposnews_metrics']['providers']['search_console']['attempted_at'] = '2020-01-01T00:00:00+00:00'
    holdings.write('owner', data)
    with patch.object(metrics, '_credentials', return_value=token()), patch.object(
            metrics, 'search_console', side_effect=ValueError('TEST-private secret')):
        result = metrics.refresh('owner', {'provider': 'search_console'})
    provider = result['providers']['search_console']
    assert provider['stale'] and provider['status'] == 'ERROR'
    assert provider['data']['totals']['clicks'] == 17 and provider['checked_at'] == checked
    assert 'TEST-private' not in str(result)


def test_other_owner_and_foreign_account_are_rejected_without_google_calls(store):
    with patch.object(metrics, '_credentials') as credentials:
        with pytest.raises(ValueError, match='OWNER_REQUIRED'):
            metrics.refresh('other', {'provider': 'search_console'})
        with pytest.raises(ValueError, match='GOOGLE_ACCOUNT_NOT_LINKED'):
            metrics.refresh('owner', {'provider': 'search_console', 'account_id': 'foreign'})
    credentials.assert_not_called()


def test_selected_account_loads_its_token_without_changing_active_account(store):
    def credentials(value):
        return Credentials(token=value, refresh_token='TEST-refresh', token_uri='https://oauth2.googleapis.com/token',
                           client_id='TEST-client', client_secret='TEST-secret',
                           scopes=list(metrics.SERVICES.values()), expiry=datetime.now(timezone.utc) + timedelta(hours=1))
    first = google_accounts.attach('owner', credentials('TEST-first'), 'first@example.test')
    second = google_accounts.attach('owner', credentials('TEST-second'), 'second@example.test')
    assert cloud_auth.get_credentials(user_id='owner', account_id=first).token == 'TEST-first'
    assert google_accounts.read('owner')['active'] == second
    with pytest.raises(ValueError, match='GOOGLE_ACCOUNT_NOT_LINKED'):
        cloud_auth.get_credentials(user_id='other', account_id=first)
    with patch.object(metrics, 'search_console', return_value={'totals': traffic()}):
        result = metrics.refresh('owner', {'provider': 'search_console', 'account_id': first})
    assert result['providers']['search_console']['selected_account'] == first
    assert google_accounts.read('owner')['active'] == second
    assert 'TEST-first' not in str(result)


def test_missing_scope_never_queries_a_provider(store):
    with patch.object(cloud_auth, 'get_credentials', return_value=SimpleNamespace(token='TEST', scopes=[])):
        with pytest.raises(metrics.MetricsError, match='NEEDS_PERMISSION'):
            metrics._credentials('owner', 'search_console', None)


def test_existing_workflow_route_requires_csrf_for_metrics(store):
    app = Flask(__name__)
    app.secret_key = 'TEST-session'
    business_workflows.register(app, lambda: 'owner')
    client = app.test_client()
    url = '/api/holdings/workflows/reposnews_metrics_view'
    assert client.post(url, json={}).status_code == 403
    with client.session_transaction() as session:
        session['business_csrf'] = 'TEST'
    result = client.post(url, json={}, headers={'X-ZAR-Business-CSRF': 'TEST'})
    assert result.status_code == 200
    assert result.json['result']['property'] == metrics.PROPERTY


def test_oauth_site_metrics_requests_only_the_two_read_permissions():
    with patch.object(cloud_auth, '_oauth_client', return_value=('TEST', 'TEST')), patch.object(
            cloud_auth, 'get_credentials', return_value=None):
        url, _, _ = cloud_auth.authorization_url(service='site_metrics', redirect_uri='https://example.test/oauth2callback')
    from urllib.parse import parse_qs, urlsplit
    scopes = set(parse_qs(urlsplit(url).query)['scope'][0].split())
    assert scopes == {'openid', 'email', *metrics.SERVICES.values()}
