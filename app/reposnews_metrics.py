"""Owner-scoped Search Console traffic and AdSense approval, with bounded caching."""
import math
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo

import requests

from . import cloud_auth, google_accounts, holdings, reposnews as rn
from .adsense_adapter import AdSenseAdapter

PROPERTY = 'sc-domain:reposnews.com'
SERVICES = {
    'search_console': 'https://www.googleapis.com/auth/webmasters.readonly',
    'adsense': 'https://www.googleapis.com/auth/adsense.readonly',
}
CONNECT_URL = '/connect/google?force=1&purpose=accounts&service=site_metrics'
CACHE_SECONDS = 300
LEASE_SECONDS = 180


class MetricsError(ValueError):
    pass


def _owner(scope):
    data = rn.read()
    if not scope or data.get('owner') != scope:
        raise ValueError('OWNER_REQUIRED')
    return data


def _epoch(value):
    try:
        return datetime.fromisoformat(value).timestamp()
    except (ValueError, TypeError):
        return 0


def view(scope):
    _owner(scope)
    cached = holdings.read(scope).get('reposnews_metrics', {})
    accounts = google_accounts.view(scope)
    active = next((a['id'] for a in accounts if a['active']), None)
    providers = {}
    now = datetime.now(timezone.utc).timestamp()
    for service in SERVICES:
        selected = cached.get('selected_accounts', {}).get(service)
        account_key = selected or active or 'current'
        record = cached.get('providers', {}).get(service, {})
        if record.get('account_key') != account_key:
            record = {}
        providers[service] = {
            'status': record.get('status', 'NOT_CONNECTED'),
            'data': record.get('data'),
            'checked_at': record.get('checked_at'),
            'attempted_at': record.get('attempted_at'),
            'error': record.get('error'),
            'selected_account': selected,
            'loading': record.get('lease_until', 0) > now,
            'stale': bool(record.get('data')) and (
                record.get('status') != 'READY' or now - _epoch(record.get('checked_at')) >= CACHE_SECONDS),
        }
    return {
        'property': PROPERTY, 'domain': 'reposnews.com', 'providers': providers,
        'accounts': accounts, 'connect_url': CONNECT_URL, 'cache_seconds': CACHE_SECONDS,
    }


def _credentials(scope, service, account_id):
    creds = cloud_auth.get_credentials(user_id=scope, account_id=account_id)
    if not creds or not creds.token:
        raise MetricsError('NOT_CONNECTED')
    granted = set(creds.scopes or [])
    full_scope = SERVICES[service].replace('.readonly', '')
    if not granted.intersection({SERVICES[service], full_scope}):
        raise MetricsError('NEEDS_PERMISSION')
    return creds


def _number(value):
    if isinstance(value, bool):
        raise MetricsError('INVALID_PROVIDER_DATA')
    try:
        number = float(value)
    except (ValueError, TypeError):
        raise MetricsError('INVALID_PROVIDER_DATA') from None
    if not math.isfinite(number) or number < 0:
        raise MetricsError('INVALID_PROVIDER_DATA')
    return number


def _traffic(row):
    return {key: _number(row[key]) for key in ('clicks', 'impressions', 'ctr', 'position')}


def _query(creds, body):
    url = 'https://www.googleapis.com/webmasters/v3/sites/' + quote(PROPERTY, safe='') + '/searchAnalytics/query'
    response = requests.post(
        url, json=body, headers={'Authorization': 'Bearer ' + creds.token},
        timeout=(5, 20), allow_redirects=False,
    )
    if response.status_code in {401, 403}:
        raise MetricsError('NEEDS_PERMISSION')
    if not response.ok:
        raise MetricsError('PROVIDER_UNAVAILABLE')
    result = response.json()
    if not isinstance(result, dict) or not isinstance(result.get('rows', []), list):
        raise MetricsError('INVALID_PROVIDER_DATA')
    return result


def search_console(creds, now=None):
    today = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo('America/Los_Angeles')).date()
    start = today - timedelta(days=27)
    body = {'startDate': start.isoformat(), 'endDate': today.isoformat(),
            'type': 'web', 'dataState': 'all', 'aggregationType': 'byProperty'}
    totals = _query(creds, body)
    daily = _query(creds, dict(body, dimensions=['date'], rowLimit=28))
    previous = _query(creds, dict(body, startDate=(start - timedelta(days=28)).isoformat(),
                                  endDate=(start - timedelta(days=1)).isoformat()))
    pages = _query(creds, dict(body, dimensions=['page'], aggregationType='byPage', rowLimit=10))
    days = []
    for row in daily.get('rows', []):
        day = row['keys'][0]
        if not start.isoformat() <= day <= today.isoformat():
            raise MetricsError('INVALID_PROVIDER_DATA')
        days.append(dict(date=day, **_traffic(row)))
    popular = []
    for row in pages.get('rows', []):
        url = row['keys'][0]
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.netloc not in {'reposnews.com', 'www.reposnews.com'}:
            continue
        popular.append(dict(url=url, **_traffic(row)))
    return {
        'source': 'Google Search Console API', 'property': PROPERTY,
        'start_date': start.isoformat(), 'end_date': today.isoformat(),
        'timezone': 'America/Los_Angeles', 'data_state': 'all',
        'totals': _traffic(totals['rows'][0]) if totals.get('rows') else None,
        'previous': _traffic(previous['rows'][0]) if previous.get('rows') else None,
        'daily': sorted(days, key=lambda row: row['date']),
        'top_pages': popular,
        'first_incomplete_date': daily.get('metadata', {}).get('first_incomplete_date'),
        'latest_date': max((row['date'] for row in days), default=None),
        'empty': not totals.get('rows'),
    }


def adsense(creds, data):
    adapter = AdSenseAdapter(credentials=creds)
    accounts = adapter.accounts()
    publisher = data.get('publisher', '')
    matching = [a for a in accounts if a.get('name') == 'accounts/' + publisher] if publisher else []
    if matching:
        account = matching[0]
    elif len(accounts) == 1:
        account = accounts[0]
    elif not accounts:
        return {'source': 'Google AdSense API', 'account_state': 'NO_ACCOUNT',
                'site_state': 'NOT_ADDED', 'auto_ads_enabled': None}
    else:
        raise MetricsError('ACCOUNT_AMBIGUOUS')
    if publisher and account.get('name') != 'accounts/' + publisher:
        raise MetricsError('PUBLISHER_MISMATCH')
    sites = adapter.collection(account['name'] + '/sites', 'sites')
    matches = [s for s in sites if str(s.get('domain', '')).lower().rstrip('.') in
               {'reposnews.com', 'www.reposnews.com'}]
    states = {s.get('state', 'STATE_UNSPECIFIED') for s in matches}
    return {
        'source': 'Google AdSense API',
        'account_state': account.get('state', 'STATE_UNSPECIFIED'),
        'site_state': next(iter(states)) if len(states) == 1 else 'NOT_ADDED' if not states else 'MULTIPLE_SITE_STATES',
        'sites': [{k: site.get(k) for k in ('domain', 'state', 'autoAdsEnabled')} for site in matches],
        'auto_ads_enabled': any(s.get('autoAdsEnabled') is True for s in matches) if matches else None,
    }


def refresh(scope, payload):
    data = _owner(scope)
    service = payload.get('provider')
    if service not in SERVICES:
        raise ValueError('INVALID_METRICS_PROVIDER')
    accounts = google_accounts.view(scope)
    selected = payload.get('account_id')
    if 'account_id' in payload and selected is not None and selected not in {a['id'] for a in accounts}:
        raise ValueError('GOOGLE_ACCOUNT_NOT_LINKED')
    token = secrets.token_hex(16)
    now = datetime.now(timezone.utc).timestamp()
    with holdings.transaction(scope):
        state = holdings.read(scope)
        cached = state.setdefault('reposnews_metrics', {})
        selection = cached.setdefault('selected_accounts', {})
        if 'account_id' in payload:
            selection[service] = selected
        selected = selection.get(service)
        active = next((a['id'] for a in accounts if a['active']), None)
        account_key = selected or active or 'current'
        record = cached.setdefault('providers', {}).get(service, {})
        if record.get('account_key') != account_key:
            record = {}
        age = now - _epoch(record.get('attempted_at'))
        ttl = CACHE_SECONDS if record.get('status') == 'READY' else 60
        if record.get('lease_until', 0) > now or age < (30 if payload.get('refresh') is True else ttl):
            holdings.write(scope, state)
            return view(scope)
        record.update(token=token, account_key=account_key, attempted_at=holdings._now(),
                      lease_until=now + LEASE_SECONDS)
        cached['providers'][service] = record
        holdings.write(scope, state)
    outcome = {'status': 'ERROR', 'error': 'PROVIDER_UNAVAILABLE'}
    try:
        creds = _credentials(scope, service, selected)
        result = search_console(creds) if service == 'search_console' else adsense(creds, data)
        if service == 'search_console':
            titles = {}
            for article in data.get('articles', []):
                if not article.get('published'):
                    continue
                published = article.get('published_snapshot', article)
                for language in ('es', 'en'):
                    canonical = published.get('seo', {}).get(language, {}).get('canonical')
                    if canonical:
                        titles[canonical.rstrip('/')] = published.get('title_' + language)
            for page in result.get('top_pages', []):
                page['title'] = titles.get(page['url'].rstrip('/'))
        outcome = {'status': 'READY', 'data': result, 'checked_at': holdings._now(), 'error': None}
    except MetricsError as exc:
        code = str(exc)
        outcome = {'status': code if code in {'NOT_CONNECTED', 'NEEDS_PERMISSION'} else 'ERROR', 'error': code}
    except (ValueError, KeyError, TypeError, IndexError, OSError, requests.RequestException):
        # Never echo Google's response, tokens or private configuration in errors.
        outcome = {'status': 'ERROR', 'error': 'PROVIDER_UNAVAILABLE'}
    finally:
        with holdings.transaction(scope):
            state = holdings.read(scope)
            record = state['reposnews_metrics']['providers'][service]
            if record.get('token') == token:
                # Keep the last successful data when the next read fails.
                record.update(outcome, lease_until=0)
                holdings.write(scope, state)
    return view(scope)
