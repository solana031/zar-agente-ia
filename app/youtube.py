from pathlib import Path
from datetime import datetime, timezone

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from .youtube_auth import get_credentials, status as youtube_auth_status

YOUTUBE_SCOPE = 'https://www.googleapis.com/auth/youtube.upload'


def _service():
    creds = get_credentials(auto_refresh=True)
    if not creds:
        raise RuntimeError('YouTube no está conectado. Pulsa «Conectar YouTube» y autoriza el permiso de YouTube.')
    scopes = set(creds.scopes or [])
    if scopes and YOUTUBE_SCOPE not in scopes:
        raise RuntimeError('Falta el permiso youtube.upload. Pulsa «Conectar YouTube» y vuelve a autorizar YouTube.')
    return build('youtube', 'v3', credentials=creds, cache_discovery=False)


def status():
    s = youtube_auth_status()
    if not s.get('connected'):
        return {
            'connected': False,
            'channel': None,
            'missing_scope': bool(s.get('missing_scope')),
            'error': s.get('error','')
        }
    try:
        yt = _service()
        data = yt.channels().list(part='snippet,contentDetails', mine=True).execute()
        item = (data.get('items') or [None])[0]
        if not item:
            return {'connected': False, 'channel': None, 'missing_scope': False, 'error': 'La cuenta de Google autorizada no tiene un canal de YouTube disponible.'}
        sn = item.get('snippet', {})
        return {'connected': True, 'channel': {'id': item.get('id'), 'title': sn.get('title',''), 'thumbnail': (sn.get('thumbnails') or {}).get('default',{}).get('url')}, 'missing_scope': False, 'error': ''}
    except HttpError as exc:
        return {'connected': False, 'channel': None, 'missing_scope': False, 'error': str(exc)}
    except Exception as exc:
        return {'connected': False, 'channel': None, 'missing_scope': False, 'error': str(exc)}


def _rfc3339(value):
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith('Z'):
            text = text[:-1] + '+00:00'
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace('+00:00','Z')


def upload(video_path, title, description='', tags=None, privacy='public', publish_at=None, category_id='22', made_for_kids=False):
    path = Path(video_path)
    if not path.exists() or path.stat().st_size == 0:
        raise FileNotFoundError('El vídeo renderizado no existe o está vacío.')
    yt = _service()
    status_body = {'privacyStatus': 'private' if publish_at else (privacy or 'public'), 'selfDeclaredMadeForKids': bool(made_for_kids)}
    if publish_at:
        status_body['publishAt'] = _rfc3339(publish_at)
    body = {
        'snippet': {
            'title': (title or path.stem or 'Vídeo de Zar')[:100],
            'description': (description or '')[:5000],
            'tags': [str(x)[:500] for x in (tags or []) if str(x).strip()][:500],
            'categoryId': str(category_id or '22'),
        },
        'status': status_body,
    }
    media = MediaFileUpload(str(path), mimetype='video/mp4', resumable=True)
    req = yt.videos().insert(part='snippet,status', body=body, media_body=media)
    response = None
    while response is None:
        _, response = req.next_chunk()
    return response


def video_status(video_id):
    yt = _service()
    data = yt.videos().list(part='status,processingDetails,snippet', id=video_id).execute()
    item = (data.get('items') or [None])[0]
    if not item:
        raise RuntimeError('YouTube no devolvió información del vídeo.')
    return item
