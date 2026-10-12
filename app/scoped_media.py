"""Private storage for legacy editors; historical files require existing ownership proof."""
import os
import re
from pathlib import Path
from .user_scope import get_current_user, safe_slug, anonymous_id


def legacy_owner():
    marker = Path(os.environ.get('ZAR_DATA_DIR', '/data')) / 'legacy_owner_browser.txt'
    if not marker.is_file():
        return False
    owner = marker.read_text(encoding='utf-8').strip()
    if not owner:
        return False
    from flask import has_request_context, session
    return get_current_user() == anonymous_id(owner) or bool(
        has_request_context() and session.get('zar_browser_id') == owner)


def directory(editor, category=''):
    root = Path(os.environ.get('ZAR_DATA_DIR', '/data')) / 'users' / safe_slug() / editor
    path = root / category
    path.mkdir(parents=True, exist_ok=True)
    return path


def filename(value):
    value = str(value)
    if not re.fullmatch(r'[a-zA-Z0-9_-][a-zA-Z0-9_.-]{0,199}', value) or '..' in value:
        raise ValueError('Identificador multimedia inválido.')
    return value


def file_path(editor, category, name):
    name = filename(name)
    path = directory(editor, category) / name
    legacy = Path(os.environ.get('ZAR_DATA_DIR', '/data')) / editor / category / name
    return legacy if not path.exists() and legacy.is_file() and legacy_owner() else path


def projects(editor):
    own = {p.name: p for p in directory(editor, 'projects').glob('*.json')}
    if legacy_owner():
        for p in (Path(os.environ.get('ZAR_DATA_DIR', '/data')) / editor / 'projects').glob('*.json'):
            own.setdefault(p.name, p)
    return sorted(own.values(), key=lambda p: p.stat().st_mtime, reverse=True)
