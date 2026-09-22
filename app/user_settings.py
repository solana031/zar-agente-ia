import json, os
from pathlib import Path
from .user_scope import get_current_user, safe_slug

DEFAULT = {
    'theme': 'dark',
    'language': 'es-ES',
    'compact_sidebar': False,
}

def _path(user_id=None):
    root = Path(os.environ.get('ZAR_DATA_DIR', '/data'))
    return root / 'users' / safe_slug(user_id or get_current_user()) / 'settings.json'

def load_settings(user_id=None):
    data = dict(DEFAULT)
    try:
        p = _path(user_id)
        if p.exists():
            raw = json.loads(p.read_text(encoding='utf-8'))
            if isinstance(raw, dict):
                for k in DEFAULT:
                    if k in raw:
                        data[k] = raw[k]
    except Exception:
        pass
    if data.get('theme') not in ('dark','light'):
        data['theme'] = 'dark'
    if not isinstance(data.get('language'), str) or not data['language']:
        data['language'] = 'es-ES'
    return data

def save_settings(updates, user_id=None):
    data = load_settings(user_id)
    for k in DEFAULT:
        if k in updates:
            data[k] = updates[k]
    p = _path(user_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(p)
    return data
