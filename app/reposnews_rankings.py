"""Ranking signals for the public ReposNews listing: GitHub stars and page views.

Stars are refreshed for one published article per cycle (at most daily per article)
from the public GitHub API and stored as presentation metadata, which does not
change an article's editorial revision.
"""
import os
import re
import time
from datetime import datetime, timezone

import requests

from . import holdings, reposnews as rn

REFRESH_SECONDS = 86400
_last = 0
_views_cache = {'at': 0, 'data': {}}


def _repo(article):
    url = str(article.get('repository_url') or '')
    m = re.match(r'https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/?$', url)
    if m:
        return m.group(1)
    repo = str(article.get('repo') or '')
    return repo if re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo) else None


def tick():
    global _last
    if time.time() - _last < 60:
        return
    _last = time.time()
    data = rn.read()
    now = time.time()
    target = next((a for a in sorted(data.get('articles', []), key=lambda a: a.get('github_checked', 0))
                   if a.get('published') and _repo(a) and now - a.get('github_checked', 0) > REFRESH_SECONDS), None)
    if not target:
        return
    headers = {'Accept': 'application/vnd.github+json'}
    if os.environ.get('GITHUB_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['GITHUB_TOKEN']
    stars = None
    try:
        r = requests.get('https://api.github.com/repos/' + _repo(target), headers=headers, timeout=(5, 15), allow_redirects=True)
        if r.ok:
            stars = int(r.json().get('stargazers_count') or 0)
        elif r.status_code in (403, 429):
            _last = time.time() + 1800  # rate limited: back off
            return
    except (requests.RequestException, ValueError, TypeError):
        return
    with holdings.transaction('reposnews-editorial'):
        data = rn.read()
        article = next((a for a in data.get('articles', []) if a['id'] == target['id']), None)
        if not article:
            return
        article['github_checked'] = now
        if stars is not None:
            article['github_stars'] = stars
            if isinstance(article.get('published_snapshot'), dict):
                article['published_snapshot']['github_stars'] = stars
        rn.write(data)


def article_views(days=30):
    if time.time() - _views_cache['at'] < 60:
        return _views_cache['data']
    from . import site_stats
    views = {}
    try:
        summary = site_stats.summary(days, top=10000)
    except Exception:
        summary = {'top': []}
    for path, count in summary['top']:
        m = re.fullmatch(r'/(?:es/repositorios|en/repositories)/([a-z0-9-]+)/', path)
        if m:
            views[m.group(1)] = views.get(m.group(1), 0) + count
    _views_cache.update(at=time.time(), data=views)
    return views


SORTS = ('recientes', 'visitas', 'novedades', 'estrellas', 'antiguos')


def _stamp(value):
    return str(value or '')


def sort_rows(rows, order):
    if order == 'antiguos':
        return sorted(rows, key=lambda a: _stamp(a.get('published_at')))
    if order == 'novedades':
        return sorted(rows, key=lambda a: max(_stamp(a.get('updated_at')), _stamp(a.get('published_at'))), reverse=True)
    if order == 'estrellas':
        return sorted(rows, key=lambda a: (a.get('github_stars') or -1, _stamp(a.get('published_at'))), reverse=True)
    if order == 'visitas':
        views = article_views()
        return sorted(rows, key=lambda a: (views.get(a['id'], 0), _stamp(a.get('published_at'))), reverse=True)
    return sorted(rows, key=lambda a: _stamp(a.get('published_at')), reverse=True)
