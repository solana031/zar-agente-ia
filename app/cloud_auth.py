import json
import os
import secrets
import threading
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

import requests
from pathlib import Path
from .user_scope import get_current_user, safe_slug

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get('ZAR_DATA_DIR', str(ROOT / 'data')))
DATA_DIR.mkdir(parents=True, exist_ok=True)
TOKEN_FILE = DATA_DIR / 'google_token.json'

def _token_file(user_id=None):
    uid = safe_slug(user_id or get_current_user())
    return DATA_DIR / 'users' / uid / 'google_token.json'

def youtube_user_id(user_id=None):
    return safe_slug(user_id or get_current_user())+'__youtube_oauth'

def _legacy_token_file():
    return TOKEN_FILE

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.compose',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/presentations',
    'https://www.googleapis.com/auth/forms.body',
    'https://www.googleapis.com/auth/contacts',
    # Google Tasks: lectura para consultar tareas/recordatorios sin conceder
    # permisos de escritura innecesarios.
    'https://www.googleapis.com/auth/tasks.readonly',
]
CORE_SCOPES=['openid','email','https://www.googleapis.com/auth/gmail.modify',
             'https://www.googleapis.com/auth/drive.file','https://www.googleapis.com/auth/drive.readonly',
             'https://www.googleapis.com/auth/calendar','https://www.googleapis.com/auth/contacts']
SERVICE_SCOPES={'core':CORE_SCOPES,'docs':['https://www.googleapis.com/auth/documents'],
 'sheets':['https://www.googleapis.com/auth/spreadsheets'],'slides':['https://www.googleapis.com/auth/presentations'],
 'tasks':['https://www.googleapis.com/auth/tasks.readonly'],
 'youtube':['https://www.googleapis.com/auth/youtube.readonly','https://www.googleapis.com/auth/youtube.upload'],
 'adsense':['https://www.googleapis.com/auth/adsense.readonly']}

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


def _save_credentials(creds, user_id=None):
    global _LAST_ERROR
    path = _token_file(user_id)
    from .oauth_vault import persist
    persist(path,creds.to_json(),DATA_DIR)
    _LAST_ERROR = ''


def get_credentials(auto_refresh=True, user_id=None):
    """Load persisted Google credentials and refresh expired access tokens automatically."""
    global _LAST_ERROR
    with _LOCK:
        path = _token_file(user_id)
        if not path.exists():
            # Backward compatibility: only the first/default workspace may adopt the old token.
            if (user_id or get_current_user()) in ('anonymous', '') and TOKEN_FILE.exists():
                path = TOKEN_FILE
            else:
                return None
        try:
            from .oauth_vault import decode
            raw=path.read_text(encoding='utf-8')
            info=decode(raw,DATA_DIR)
            creds = Credentials.from_authorized_user_info(info, info.get('scopes') or [])
            if json.loads(raw).get('format')!='ZAR_OAUTH_ENCRYPTED_V1':
                from .oauth_vault import persist
                persist(path,creds.to_json(),DATA_DIR)
                _save_credentials(creds,user_id=user_id)
        except Exception as exc:
            _LAST_ERROR = str(exc)
            return None

        # If the token is expired but a refresh token exists, refresh it silently.
        # This is what lets Gmail/Calendar keep working after the short-lived access
        # token expires, without showing the Google consent screen again.
        if auto_refresh and creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                _save_credentials(creds, user_id=user_id)
            except RefreshError as exc:
                _LAST_ERROR = str(exc)
                return None
            except Exception as exc:
                _LAST_ERROR = str(exc)
                return None
        return creds


def _missing_scopes(creds):
    if not creds:
        return list(SCOPES)
    granted = set(creds.scopes or [])
    # Some credential files do not expose scopes. In that case rely on the token
    # itself and let Google API return a precise permission error when needed.
    if not granted:
        return list(SCOPES)
    if 'https://www.googleapis.com/auth/gmail.modify' in granted:
        granted.update(['https://www.googleapis.com/auth/gmail.readonly','https://www.googleapis.com/auth/gmail.compose'])
    return [scope for scope in SCOPES if scope not in granted]


def auth_status():
    """Return a UI-safe Google connection status; never exposes secrets."""
    creds = get_credentials(auto_refresh=True)
    missing = _missing_scopes(creds)
    connected_ok = bool(creds and (creds.valid or creds.refresh_token))
    expires_at = None
    if creds and creds.expiry:
        expires_at = creds.expiry.astimezone(timezone.utc).isoformat()
    email = get_account_email(creds) if connected_ok else ''
    granted=set(creds.scopes or []) if creds else set()
    # Google returns the canonical userinfo.email URL for the email alias.
    if 'https://www.googleapis.com/auth/userinfo.email' in granted:granted.add('email')
    return {
        'email': email,
        'connected': connected_ok,
        'has_token': bool(creds),
        'has_refresh_token': bool(creds and creds.refresh_token),
        'missing_scopes': missing,
        'expires_at': expires_at,
        'needs_reauth': bool((creds is None and (_token_file().exists() or TOKEN_FILE.exists())) or
                             (creds and not set(CORE_SCOPES).issubset(granted))),
        'error': _LAST_ERROR if not connected_ok else '',
    }


def _oauth_client():
    """Return the OAuth client settings for a web client."""
    cfg = _client_config()
    # Google client JSON can contain either a `web` or `installed` block.
    client = cfg.get('web') or cfg.get('installed') or cfg
    client_id = str(client.get('client_id') or '').strip()
    client_secret = str(client.get('client_secret') or '').strip()
    if not client_id:
        raise ValueError('El credentials.json/GOOGLE_CLIENT_CONFIG_JSON no contiene client_id.')
    if not client_secret:
        raise ValueError('El cliente OAuth web no contiene client_secret.')
    return client_id, client_secret


def authorization_url(force=False, redirect_uri=None, service=None, expected_email=None):
    """Build Google's OAuth authorization URL explicitly.

    This intentionally avoids delegating the authorization-request construction
    to google-auth-oauthlib. Zar controls every OAuth parameter so the browser
    request and the later token exchange use the exact same redirect URI and
    PKCE verifier. This is particularly useful on Railway, where multiple host
    aliases can otherwise produce subtle redirect/state mismatches.
    """
    client_id, _ = _oauth_client()
    redirect = (redirect_uri or _redirect_uri()).strip()
    if not redirect:
        raise ValueError('Falta GOOGLE_REDIRECT_URI o una URI de redirección válida.')

    # RFC 7636: 43-128 characters, URL-safe. The SHA-256 challenge is generated
    # by Google from this verifier when code_challenge_method=S256 is supplied.
    code_verifier = secrets.token_urlsafe(48)
    import hashlib
    import base64
    digest = hashlib.sha256(code_verifier.encode('ascii')).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')
    state = secrets.token_urlsafe(32)

    requested_scopes = (['openid','email']+SERVICE_SCOPES[service]) if service else list(SCOPES)
    if service != 'youtube':
        previous = get_credentials(auto_refresh=False)
        allowed = set(SCOPES + CORE_SCOPES + [s for name, values in SERVICE_SCOPES.items() if name != 'youtube' for s in values])
        if previous:
            requested_scopes = list(dict.fromkeys(requested_scopes + [s for s in (previous.scopes or []) if s in allowed and '/youtube' not in s]))

    params = {
        'client_id': client_id,
        'redirect_uri': redirect,
        'response_type': 'code',
        'scope': ' '.join(requested_scopes),
        'state': state,
        'access_type': 'offline',
        'code_challenge': code_challenge,
        'code_challenge_method': 'S256',
        # Google rejects drive.file + YouTube grants, including implicit accumulation.
        # Workspace scopes may accumulate only the grants already stored in its
        # own credential file; YouTube remains in its separate credential file.
        'include_granted_scopes': 'false',
    }
    if force:
        params['prompt'] = 'consent select_account'
    if expected_email:params['login_hint']=expected_email

    url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode(params)
    return url, state, code_verifier


def finish_oauth(state, code, code_verifier, redirect_uri=None, user_id=None, expected_email=None):
    """Exchange the authorization code for Google user credentials."""
    if not code_verifier:
        raise ValueError('Falta el verificador PKCE de la sesión OAuth.')
    client_id, client_secret = _oauth_client()
    redirect = (redirect_uri or _redirect_uri()).strip()
    if not redirect:
        raise ValueError('Falta la URI de redirección para completar OAuth.')

    token_response = requests.post(
        'https://oauth2.googleapis.com/token',
        data={
            'code': code,
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': redirect,
            'grant_type': 'authorization_code',
            'code_verifier': code_verifier,
        },
        timeout=30,
    )
    try:
        payload = token_response.json()
    except Exception:
        payload = {'error': token_response.text}
    if not token_response.ok:
        err = payload.get('error_description') or payload.get('error') or f'HTTP {token_response.status_code}'
        raise RuntimeError(f'Google rechazó el intercambio OAuth: {err}')

    access_token = payload.get('access_token')
    if not access_token:
        raise RuntimeError('Google no devolvió access_token.')

    expires_in = int(payload.get('expires_in') or 3600)
    expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    creds = Credentials(
        token=access_token,
        refresh_token=payload.get('refresh_token'),
        token_uri='https://oauth2.googleapis.com/token',
        client_id=client_id,
        client_secret=client_secret,
        scopes=payload.get('scope', '').split(),
        expiry=expiry,
    )
    if expected_email and get_account_email(creds)!=expected_email.strip().lower():
        raise ValueError('La identidad OAuth no coincide con la cuenta ZAR seleccionada. No se han sustituido tokens.')
    if not creds.refresh_token:
        previous=get_credentials(auto_refresh=False,user_id=user_id)
        if previous and previous.refresh_token and previous.client_id==creds.client_id:
            new_email=get_account_email(creds)
            if new_email and get_account_email(previous)==new_email:
                creds=Credentials(token=creds.token,refresh_token=previous.refresh_token,token_uri=creds.token_uri,
                    client_id=creds.client_id,client_secret=creds.client_secret,scopes=creds.scopes,expiry=creds.expiry)
    _save_credentials(creds, user_id=user_id)
    return creds



def get_account_email(creds=None):
    """Return the Google account email represented by the current OAuth token."""
    c = creds or get_credentials(auto_refresh=True)
    if not c or not c.token:
        return ''
    try:
        r = requests.get('https://www.googleapis.com/oauth2/v3/userinfo', headers={'Authorization': f'Bearer {c.token}'}, timeout=15)
        if r.ok:
            return (r.json().get('email') or '').strip().lower()
    except Exception:
        pass
    return ''

def connected():
    status = auth_status()
    return bool(status['connected'])
