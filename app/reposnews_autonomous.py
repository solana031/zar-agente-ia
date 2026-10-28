"""Owner-authorized weekday fallback. Durable jobs; no browser or Codex dependency."""
import logging
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import requests
from flask import has_request_context, session
from . import holdings, reposnews as rn

MADRID = ZoneInfo('Europe/Madrid')
TRENDING = 'https://github.com/trending?since=monthly'
TERMINAL = {'COMPLETED', 'PARTIAL', 'SKIPPED_REELS', 'NO_VERIFIED_CANDIDATES'}
_worker = None
_worker_lock = threading.Lock()


def utcnow():
    return datetime.now(timezone.utc)


def timestamp(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def next_slot(now):
    local = now.astimezone(MADRID)
    slot = local.replace(hour=18, minute=0, second=0, microsecond=0)
    if slot <= local:
        slot += timedelta(days=1)
    while slot.weekday() > 4:
        slot += timedelta(days=1)
    return slot


def reel_article_today(data, now):
    day = now.astimezone(MADRID).date()
    articles = {a['id']: a for a in data.get('articles', [])}
    for row in data.get('instagram_inbox', []):
        received = timestamp(row.get('received_at'))
        article = articles.get(row.get('article_id'))
        if (not row.get('backfill') and received and received.astimezone(MADRID).date() == day
                and article and article.get('state') not in {'CANCELLED', 'IDEA', 'RESEARCH', 'DRAFT'}):
            from .reposnews_automation import complete
            if complete(article):
                return True
    return False


def configure(scope, payload):
    if not has_request_context() or session.get('zar_auth') is not True:
        raise ValueError('AUTHENTICATED_OWNER_REQUIRED')
    if payload.get('enabled') not in (True, False) or not isinstance(payload.get('enabled'), bool):
        raise ValueError('EXPLICIT_POLICY_CHOICE_REQUIRED')
    if payload['enabled'] and payload.get('authorize_publication') is not True:
        raise ValueError('AUTOMATIC_PUBLICATION_AUTHORIZATION_REQUIRED')
    with holdings.transaction('reposnews-editorial'):
        data = rn.read()
        if not data.get('owner') or data['owner'] != scope:
            raise ValueError('OWNER_REQUIRED')
        previous = data.get('autonomous_editorial', {})
        if payload['enabled'] and previous.get('enabled'):
            return rn.state(scope)
        now = utcnow()
        data['autonomous_editorial'] = {
            'enabled': payload['enabled'], 'owner': scope, 'grant': secrets.token_hex(16),
            'authorized_at': now.isoformat(), 'first_slot': next_slot(now).isoformat(),
            'timezone': 'Europe/Madrid', 'weekdays': [0, 1, 2, 3, 4], 'hour': 18,
            'maximum_articles': 4, 'source': TRENDING,
            'purpose': 'PUBLISH_MONTHLY_TRENDING_IF_NO_NEW_REEL_ARTICLE',
        }
        rn.write(data)
    return rn.state(scope)


def view(data, now=None):
    now = now or utcnow()
    policy = data.get('autonomous_editorial', {})
    jobs = data.get('autonomous_editorial_jobs', {})
    latest = jobs[sorted(jobs)[-1]] if jobs else {}
    return {'enabled': policy.get('enabled', False), 'timezone': 'Europe/Madrid',
            'next_run': next_slot(now).isoformat() if policy.get('enabled') else None,
            'last_status': latest.get('status', 'NOT_RUN'), 'last_day': latest.get('day'),
            'published': len(latest.get('published', [])), 'last_error': latest.get('error'),
            'source': TRENDING, 'maximum_articles': 4}


class MonthlyParser(HTMLParser):
    """Read actual monthly growth, never infer it from lifetime star counts."""
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.h2 = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'article' and 'Box-row' in attrs.get('class', '').split():
            self.row = {'text': [], 'repo': ''}
        if self.row is None:
            return
        if tag == 'h2':
            self.h2 = True
        if tag == 'a' and self.h2 and re.fullmatch(r'/[\w.-]+/[\w.-]+', attrs.get('href', '')):
            self.row['repo'] = attrs['href'][1:]

    def handle_data(self, value):
        if self.row is not None:
            self.row['text'].append(value)

    def handle_endtag(self, tag):
        if tag == 'h2':
            self.h2 = False
        if tag == 'article' and self.row is not None:
            match = re.search(r'([\d,]+)\s+stars?\s+this month', ' '.join(self.row['text']))
            if self.row['repo'] and match and int(match[1].replace(',', '')) > 0:
                self.rows.append({'repo': self.row['repo'], 'monthly_stars': int(match[1].replace(',', ''))})
            self.row = None


def monthly_candidates():
    with requests.Session() as client:
        client.trust_env = False
        with client.get(TRENDING, headers={'User-Agent': 'ReposNews-editorial/1', 'Accept-Language': 'en'},
                        timeout=(5, 20), allow_redirects=False, stream=True) as response:
            if response.status_code != 200:
                raise ValueError('MONTHLY_SOURCE_UNAVAILABLE')
            body = bytearray()
            for chunk in response.iter_content(65536):
                body.extend(chunk)
                if len(body) > 2000000:
                    raise ValueError('MONTHLY_SOURCE_TOO_LARGE')
    parser = MonthlyParser()
    parser.feed(body.decode('utf-8'))
    if not parser.rows:
        raise ValueError('MONTHLY_GROWTH_NOT_VERIFIED')
    return [dict(row, rank=i + 1, source=TRENDING, observed_at=utcnow().isoformat())
            for i, row in enumerate(parser.rows[:20])]


def due(data, now):
    policy = data.get('autonomous_editorial', {})
    first = timestamp(policy.get('first_slot'))
    local = now.astimezone(MADRID)
    return bool(data.get('owner') and policy.get('enabled') and policy.get('owner') == data['owner']
                and first and now >= first and local.weekday() < 5 and local.hour >= 18)


def authorized(article, scope, data=None, now=None):
    """Narrow standing grant: only this owner's current job and exact reviewed revision."""
    from .reposnews_automation import revision
    data = data if data is not None else rn.read()
    now = now or utcnow()
    policy = data.get('autonomous_editorial', {})
    auth = article.get('autonomous_authorization', {})
    job = data.get('autonomous_editorial_jobs', {}).get(auth.get('day'), {})
    proof = job.get('prepared', {}).get(article.get('id'), {})
    trend = article.get('monthly_trend', {})
    observed = timestamp(trend.get('observed_at'))
    return bool(due(data, now) and scope == data.get('owner') and auth.get('grant') == policy.get('grant')
                and auth.get('grant') == job.get('grant') and job.get('status') == 'RUNNING'
                and job.get('lease_until', 0) > now.timestamp()
                and auth.get('day') == now.astimezone(MADRID).date().isoformat()
                and proof.get('revision') == revision(article) and proof.get('repo') == article.get('repo')
                and article.get('approval_status') == 'OWNER_AUTHORIZED_SCHEDULE'
                and article.get('review_kind') == 'AUTOMATED_SOURCE_REVIEW'
                and all(article.get('review', {}).get(k) is True for k in ('supported', 'commands_supported', 'privacy_safe'))
                and trend.get('source') == TRENDING and trend.get('repo') == article.get('repo')
                and isinstance(trend.get('monthly_stars'), int) and trend['monthly_stars'] > 0
                and observed and observed.astimezone(MADRID).date() == now.astimezone(MADRID).date()
                and len(job.get('published', [])) < 4 and not reel_article_today(data, now))


def prepare(candidate):
    from . import reposnews_inbox as inbox, reposnews_covers as covers
    from .reposnews_cover_providers import editorial
    package = inbox.research(candidate['repo'])
    # A repaired/redirected repository must qualify independently on the monthly list.
    if package['repo'].casefold() != candidate['repo'].casefold():
        raise ValueError('MONTHLY_REPOSITORY_CHANGED')
    package['monthly_trend'] = candidate
    article = inbox.build(package, 'GITHUB_MONTHLY_TRENDING')
    blob, provider = editorial(article)
    covers.persist(article, blob, 'GENERATED', generator=provider)
    article['monthly_trend'] = candidate
    return article


def tick(now=None):
    """One bounded daily job. Claims and commits are serialized across server processes."""
    from . import reposnews_automation as automation
    now = now or utcnow()
    day = now.astimezone(MADRID).date().isoformat()
    token = secrets.token_hex(16)
    with holdings.transaction('reposnews-editorial'):
        data = rn.read()
        if not due(data, now) or holdings.read(data['owner']).get('global_stop'):
            return
        if rn.legal_status(data)['status'] != 'LEGAL_READY':
            return
        jobs = data.setdefault('autonomous_editorial_jobs', {})
        job = jobs.setdefault(day, {'day': day, 'attempts': 0, 'published': [], 'tried': [], 'prepared': {}})
        if job.get('status') in TERMINAL or job.get('lease_until', 0) > now.timestamp() or job['attempts'] >= 2:
            return
        if job.get('retry_after', 0) > now.timestamp():
            return
        if reel_article_today(data, now):
            job['status'] = 'SKIPPED_REELS'
            rn.write(data)
            return
        job.update(status='RUNNING', token=token, grant=data['autonomous_editorial']['grant'],
                   lease_until=now.timestamp() + 2700, attempts=job['attempts'] + 1, error=None)
        # Keep a small operational history; articles retain their own provenance.
        data['autonomous_editorial_jobs'] = dict(sorted(jobs.items())[-90:])
        rn.write(data)
    try:
        candidates = monthly_candidates()
        for candidate in candidates:
            current = utcnow()
            with holdings.transaction('reposnews-editorial'):
                data = rn.read(); job = data['autonomous_editorial_jobs'][day]
                if job.get('token') != token:
                    return
                if not due(data, current) or current.astimezone(MADRID).date().isoformat() != day:
                    break
                if holdings.read(data['owner']).get('global_stop') or reel_article_today(data, current):
                    job['status'] = 'SKIPPED_REELS' if reel_article_today(data, current) else 'PAUSED'
                    rn.write(data)
                    break
                if len(job['published']) >= 4 or len(job['tried']) >= 8:
                    break
                repo = candidate['repo'].casefold()
                if repo in job['tried'] or any(str(a.get('repo', '')).casefold() == repo for a in data.get('articles', [])):
                    continue
                job['tried'].append(repo)
                job['lease_until'] = current.timestamp() + 2700
                rn.write(data)
            try:
                article = prepare(candidate)
                with holdings.transaction('reposnews-editorial'):
                    data = rn.read(); job = data['autonomous_editorial_jobs'][day]
                    if job.get('token') != token:
                        return
                    if any(a['id'] == article['id'] or str(a.get('repo', '')).casefold() == repo for a in data.get('articles', [])):
                        continue
                    article.update(approval_status='OWNER_AUTHORIZED_SCHEDULE', autonomous_authorization={'day': day, 'grant': job['grant']})
                    job['prepared'][article['id']] = {'repo': article['repo'], 'revision': automation.revision(article)}
                    if not authorized(article, data['owner'], data):
                        break
                    automation.publish_article(data, article, data['owner'])
                    data.setdefault('articles', []).append(article)
                    job['published'].append(article['id'])
                    rn.write(data)
            except (ValueError, OSError, requests.RequestException):
                # Failed candidates never publish; try other independently verified projects.
                logging.getLogger(__name__).info('ReposNews monthly candidate did not pass preparation/publication')
        with holdings.transaction('reposnews-editorial'):
            data = rn.read(); job = data['autonomous_editorial_jobs'][day]
            if job.get('token') == token:
                if job['status'] == 'RUNNING':
                    job['status'] = 'COMPLETED' if len(job['published']) >= 3 else 'PARTIAL' if job['published'] else 'NO_VERIFIED_CANDIDATES'
                job.update(lease_until=0, finished_at=utcnow().isoformat())
                rn.write(data)
    except Exception:
        logging.getLogger(__name__).error('ReposNews scheduled editorial job failed; provider details omitted')
        with holdings.transaction('reposnews-editorial'):
            data = rn.read(); job = data.get('autonomous_editorial_jobs', {}).get(day, {})
            if job.get('token') == token:
                job.update(status='FAILED_RETRYABLE', error='MONTHLY_JOB_FAILED', lease_until=0, retry_after=time.time() + 1800)
                rn.write(data)


def start_worker():
    global _worker
    with _worker_lock:
        if _worker and _worker.is_alive():
            return
        def loop():
            while True:
                try:
                    tick()
                except Exception:
                    logging.getLogger(__name__).error('ReposNews fallback worker cycle failed; provider details omitted')
                time.sleep(45)
        _worker = threading.Thread(target=loop, daemon=True, name='reposnews-autonomous-editorial')
        _worker.start()
