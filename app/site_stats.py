"""Anonymous page-view counter for www.reposnews.com.

Counts successful HTML page views per day and path. No cookies, IPs or user agents
are stored; obvious bots and monitoring tools are skipped. Counts are kept in
memory and flushed to disk by the editorial worker (and when the buffer grows).
"""
import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

BOTS = re.compile(r'bot|crawl|spider|slurp|curl|wget|python|httpx|go-http|java/|okhttp|headless|lighthouse|monitor|uptime|'
                  r'preview|facebookexternalhit|whatsapp|telegram|discord|slack|embedly|pingdom|powershell|scrapy|axios|node-fetch', re.I)
_lock = threading.Lock()
_pending = {}
KEEP_DAYS = 400


def _path():
    return Path(os.environ.get('ZAR_DATA_DIR', '/data')) / 'reposnews' / 'visits.json'


def _clean_path(path):
    path = re.sub(r'[?#].*$', '', str(path or '/'))[:200]
    if not re.fullmatch(r'/[A-Za-z0-9/_.\-]*', path) or path.startswith(('/media/', '/static/', '/api/')):
        return None
    return path if path.endswith('/') else path + '/'


def record(path, user_agent=''):
    if not user_agent or BOTS.search(user_agent):
        return
    path = _clean_path(path)
    if not path:
        return
    day = datetime.now(timezone.utc).date().isoformat()
    with _lock:
        _pending.setdefault(day, {})
        _pending[day][path] = _pending[day].get(path, 0) + 1
        size = sum(len(v) for v in _pending.values())
    if size > 300:
        flush()


def _read():
    try:
        data = json.loads(_path().read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def flush():
    with _lock:
        if not _pending:
            return
        pending = {day: dict(rows) for day, rows in _pending.items()}
        _pending.clear()
        data = _read()
        for day, rows in pending.items():
            target = data.setdefault(day, {})
            for path, count in rows.items():
                target[path] = target.get(path, 0) + count
        cutoff = (datetime.now(timezone.utc).date() - timedelta(days=KEEP_DAYS)).isoformat()
        data = {day: rows for day, rows in data.items() if day >= cutoff}
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(data, separators=(',', ':')), encoding='utf-8')
        temp.replace(path)


def summary(days=7):
    flush()
    data = _read()
    today = datetime.now(timezone.utc).date()
    current = [(today - timedelta(days=i)).isoformat() for i in range(days)]
    previous = [(today - timedelta(days=i)).isoformat() for i in range(days, days * 2)]
    pages = {}
    for day in current:
        for path, count in data.get(day, {}).items():
            pages[path] = pages.get(path, 0) + count
    return {'total': sum(pages.values()), 'previous': sum(sum(data.get(day, {}).values()) for day in previous),
            'top': sorted(pages.items(), key=lambda item: -item[1])[:10],
            'daily': [(day, sum(data.get(day, {}).values())) for day in reversed(current)]}
