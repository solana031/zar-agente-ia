import json
import os
import secrets
import threading
from pathlib import Path
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get('ZAR_DATA_DIR', str(ROOT / 'data')))
DATA_DIR.mkdir(parents=True, exist_ok=True)
TOKEN_FILE = DATA_DIR / 'youtube_token.json'
YOUTUBE_SCOPE = 'https://www.googleapis.com/auth/youtube.upload'
_LOCK = threading.RLock()
_LAST_ERROR = ''


def _client_config():
    raw = os.environ.get('GOOGLE_CLIENT_CONFIG_JSON', '').strip()
    if raw:
        return json.loads(raw)
    path = ROOT / 'credentials.json'
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    raise FileNotFoundError('Falta GOOGLE_CLIENT_CONFIG_JSON en Railway o credentials.json en local.')


def _redirect_uri():
    explicit = os.environ.get('GOOGLE_REDIRECT_URI', '').strip()
    if explicit:
        return explicit
    base = os.environ.get('PUBLIC_BASE_URL', '').strip().rstrip('/')
    if base:
        return base + '/oauth2callback'
    return 'http://127.0.0.1:8765/oauth2callback'


def _save_credentials(creds):
    global _LAST_ERROR
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = TOKEN_FILE.with_suffix('.tmp')
    tmp.write_text(creds.to_json(), encoding='utf-8')
    tmp.replace(TOKEN_FILE)
    _LAST_ERROR = ''


def get_credentials(auto_refresh=True):
    global _LAST_ERROR
    with _LOCK:
        if not TOKEN_FILE.exists():
            return None
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), [YOUTUBE_SCOPE])
        except Exception as exc:
            _LAST_ERROR = str(exc)
            return None
        if auto_refresh and creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                _save_credentials(creds)
            except RefreshError as exc:
                _LAST_ERROR = str(exc)
                return None
            except Exception as exc:
                _LAST_ERROR = str(exc)
                return None
        return creds


def status():
    creds = get_credentials(auto_refresh=True)
    granted = set(creds.scopes or []) if creds else set()
    return {
        'connected': bool(creds and (creds.valid or creds.refresh_token) and (not granted or YOUTUBE_SCOPE in granted)),
        'has_token': bool(creds),
        'has_refresh_token': bool(creds and creds.refresh_token),
        'missing_scope': bool(creds and granted and YOUTUBE_SCOPE not in granted),
        'error': _LAST_ERROR,
    }


def authorization_url(force=True):
    code_verifier = secrets.token_urlsafe(64)
    flow = Flow.from_client_config(
        _client_config(),
        scopes=[YOUTUBE_SCOPE],
        redirect_uri=_redirect_uri(),
        code_verifier=code_verifier,
        autogenerate_code_verifier=False,
    )
    params = {'access_type': 'offline', 'include_granted_scopes': 'true'}
    if force:
        params['prompt'] = 'consent'
    url, state = flow.authorization_url(**params)
    return url, state, code_verifier


def finish_oauth(state, code, code_verifier):
    if not code_verifier:
        raise ValueError('Falta el verificador PKCE de la sesión OAuth de YouTube.')
    flow = Flow.from_client_config(
        _client_config(),
        scopes=[YOUTUBE_SCOPE],
        state=state,
        redirect_uri=_redirect_uri(),
        code_verifier=code_verifier,
        autogenerate_code_verifier=False,
    )
    flow.fetch_token(code=code, code_verifier=code_verifier)
    creds = flow.credentials
    _save_credentials(creds)
    return creds
