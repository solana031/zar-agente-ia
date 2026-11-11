"""Saved provider accounts on this ZAR installation, selectable per provider.

Every time a social provider is verified as connected, ZAR keeps an encrypted copy of
that account's credential file as a profile. Selecting another profile first saves the
current one and then restores the chosen copy into the provider's active location, so
publishing/reading code keeps using its usual single active credential.

Credential files are copied byte for byte: they stay encrypted with the same vault key
they were written with and are restored to the same path. Views only expose labels.
"""
import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path

from . import holdings

PROFILE_PROVIDERS = ('youtube', 'tiktok', 'instagram')
GOOGLE_BACKED = ('google', 'adsense')


def _data_root():
    return Path(os.environ.get('ZAR_DATA_DIR', '/data'))


def _root(scope):
    from .user_scope import safe_slug
    return _data_root() / 'users' / safe_slug(scope) / 'account_profiles'


def active_path(scope, provider):
    """Location of the provider's single active credential for this scope."""
    if provider == 'youtube':
        from . import cloud_auth
        return cloud_auth._token_file(cloud_auth.youtube_user_id(scope))
    if provider == 'tiktok':
        from . import tiktok_oauth
        return tiktok_oauth._path(scope)[0]
    if provider == 'instagram':
        from . import instagram_tokens
        return instagram_tokens.path()
    raise ValueError('PROFILE_PROVIDER_UNSUPPORTED')


def _index_path(scope):
    return _root(scope) / 'index.json'


def _read(scope):
    try:
        data = json.loads(_index_path(scope).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = {}
    data.setdefault('providers', {})
    data.setdefault('active', {})
    return data


def _write(scope, data):
    path = _index_path(scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    temp.replace(path)


def _key(provider, label):
    return hashlib.sha256((provider + '|' + str(label).strip().lower()).encode()).hexdigest()[:24]


def _profile_file(scope, provider, key):
    if provider not in PROFILE_PROVIDERS or not re.fullmatch(r'[a-f0-9]{24}', str(key or '')):
        raise ValueError('PROFILE_ID_INVALID')
    return _root(scope) / provider / (key + '.cred')


def clean_label(value):
    text = re.sub(r'\s+', ' ', str(value or '')).strip()
    return text[:120]


def capture(scope, provider, label):
    """Save (or refresh) the currently active credential as a named profile."""
    label = clean_label(label)
    if provider not in PROFILE_PROVIDERS or not label:
        return None
    source = active_path(scope, provider)
    if not source.is_file():
        return None
    key = _key(provider, label)
    target = _profile_file(scope, provider, key)
    with holdings.transaction(scope):
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
        data = _read(scope)
        rows = data['providers'].setdefault(provider, {})
        rows[key] = dict(rows.get(key, {}), label=label, saved_at=holdings._now())
        data['active'][provider] = key
        _write(scope, data)
    return key


def view(scope, provider=None):
    data = _read(scope)
    result = {}
    for name in ([provider] if provider else PROFILE_PROVIDERS):
        if name not in PROFILE_PROVIDERS:
            continue
        rows = data['providers'].get(name, {})
        result[name] = [{'id': key, 'label': row.get('label'), 'saved_at': row.get('saved_at'),
                         'active': data['active'].get(name) == key}
                        for key, row in sorted(rows.items(), key=lambda item: item[1].get('label', '').lower())
                        if _profile_file(scope, name, key).is_file()]
    if provider in GOOGLE_BACKED or provider is None:
        from .google_accounts import view as google_view
        google = [{'id': row['id'], 'label': row.get('email') or 'Cuenta Google', 'saved_at': row.get('verified_at'),
                   'active': row.get('active')} for row in google_view(scope)]
        for name in GOOGLE_BACKED:
            if provider in (None, name):
                result[name] = google
    return result[provider] if provider else result


def select(scope, provider, key, current_label=None):
    """Activate a saved profile. The current credential is saved first, never lost."""
    if provider in GOOGLE_BACKED:
        from .google_accounts import select as google_select
        google_select(scope, key)
        return
    source = _profile_file(scope, provider, key)
    if not source.is_file():
        raise ValueError('PROFILE_NOT_FOUND')
    if current_label:
        capture(scope, provider, current_label)
    target = active_path(scope, provider)
    with holdings.transaction(scope):
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(target.name + '.switch')
        shutil.copyfile(source, temp)
        temp.replace(target)
        data = _read(scope)
        data['active'][provider] = key
        data.setdefault('switched_at', {})[provider] = time.time()
        _write(scope, data)


def remove(scope, provider, key):
    if provider in GOOGLE_BACKED:
        raise ValueError('PROFILE_REMOVE_GOOGLE_UNSUPPORTED')
    path = _profile_file(scope, provider, key)
    with holdings.transaction(scope):
        data = _read(scope)
        if data['active'].get(provider) == key:
            raise ValueError('PROFILE_ACTIVE')
        path.unlink(missing_ok=True)
        data['providers'].get(provider, {}).pop(key, None)
        _write(scope, data)
