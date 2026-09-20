"""Per-browser/per-Google-account identity scope for ZAR.

The active user id is carried in a ContextVar so concurrent Railway requests do not
share conversation, memory, context or Google credentials between users.
"""
import contextvars, hashlib, re

_current = contextvars.ContextVar('zar_user_id', default='')


def normalize_email(email):
    return (email or '').strip().lower()


def user_id_for_email(email):
    e = normalize_email(email)
    return 'g_' + hashlib.sha256(e.encode('utf-8')).hexdigest()[:32] if e else ''


def anonymous_id(session_id):
    s = str(session_id or '').strip()
    return 's_' + hashlib.sha256(s.encode('utf-8')).hexdigest()[:32] if s else 'anonymous'


def set_current_user(user_id):
    return _current.set(str(user_id or 'anonymous'))


def reset_current_user(token):
    try: _current.reset(token)
    except Exception: pass


def get_current_user():
    return _current.get() or 'anonymous'


def safe_slug(user_id=None):
    raw = str(user_id or get_current_user())
    return re.sub(r'[^a-zA-Z0-9_.-]+', '_', raw)[:80] or 'anonymous'
