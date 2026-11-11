"""Bounded existing-provider failover and an offline editorial canvas guarantee."""
import base64
import hashlib
import io
import json
import os
import re
import tempfile
import threading
import time
from email.utils import parsedate_to_datetime
from pathlib import Path
import requests
from PIL import Image, ImageDraw
from . import reposnews as rn
from .scoped_http import BearerAuth

_lock = threading.RLock()
INTERNAL = 'ReposNews/internal-editorial-canvas-v2'
LEGACY_INTERNAL = ('ReposNews/internal-editorial-canvas-v1',)


class ProviderError(ValueError):
    def __init__(self, code, retry_after=None):
        super().__init__(code)
        try:
            delay = int(retry_after)
        except (ValueError, TypeError):
            try: delay = parsedate_to_datetime(retry_after).timestamp() - time.time()
            except (ValueError, TypeError, OverflowError): delay = 600
        self.retry_after = max(600, min(86400, delay))


def editorial(article, analysis=None):
    """Unique "how it works" illustration from the article/Reel; never a screenshot or logo.

    Uses a stored or curated cover_spec; otherwise asks the configured text model once
    for one (stored on the article dict by the caller) and falls back to a
    deterministic, subject-specific spec when no provider is available.
    """
    from . import reposnews_cover_art as art
    if art.needs_spec(article):
        try:
            article['cover_spec']=art.generate_spec(article,analysis if isinstance(analysis,dict) else None)
        except Exception:  # Provider details never reach logs; heuristic spec is still unique.
            pass
    return art.render(article,art.spec_for(article)), INTERNAL


def _openrouter(article, context):
    from .config import load
    from .model_router import model_for
    cfg=load()['openrouter'];key=cfg.get('api_key')
    if not key:raise ValueError('COVER_PROVIDER_NOT_CONFIGURED')
    model=os.environ.get('ZAR_COVER_OPENROUTER_MODEL') or 'google/'+model_for('image')
    if not re.fullmatch(r'[A-Za-z0-9_./:-]+',model):raise ValueError('COVER_MODEL_INVALID')
    # Fixed official destination; never forward a configured secret to a supplied URL.
    r=requests.post('https://openrouter.ai/api/v1/images',auth=BearerAuth(key),
        json={'model':model,'prompt':context['prompt'],'aspect_ratio':'16:9','resolution':'1K','n':1},
        timeout=(5,60),allow_redirects=False)
    if not r.ok:raise ProviderError('COVER_PROVIDER_'+str(r.status_code),r.headers.get('Retry-After'))
    data=(r.json().get('data') or [{}])[0];raw=data.get('b64_json','')
    if not raw or len(raw)>16000000 or data.get('media_type','image/png') not in {'image/png','image/jpeg','image/webp'}:
        raise ValueError('COVER_PROVIDER_NO_IMAGE')
    return base64.b64decode(raw,validate=True),'OpenRouter/'+model


def _comfy(article, context):
    from .text_video_render import comfy_visual
    workflow=Path(os.environ.get('ZAR_COMFY_WORKFLOW_PATH',str(rn._path().parent.parent/'comfy-workflow.json')))
    if not workflow.is_file():raise ValueError('COVER_PROVIDER_NOT_CONFIGURED')
    with tempfile.TemporaryDirectory(prefix='zar-cover-') as folder:
        path,provider=comfy_visual({'visual_prompt':context['prompt']},Path(folder),0,workflow)
        if not path:raise ValueError('COVER_COMFY_UNAVAILABLE')
        return path.read_bytes(),provider


def generate(article, context):
    from .reposnews_generation import _gemini_article_cover
    from .reposnews_covers import quality, semantic
    path=rn._path().parent/'cover-provider-state.json'
    for name,call in [('Gemini',_gemini_article_cover),('OpenRouter',_openrouter),('ComfyUI',_comfy)]:
        with _lock:
            try:state=json.loads(path.read_text())
            except (OSError,ValueError):state={}
            if state.get(name,{}).get('retry_after',0)>time.time():continue
        try:
            blob,provider=call(article,context)
            if not quality(blob)['valid'] or not semantic(blob,article):raise ValueError('COVER_GENERATED_REJECTED')
            return blob,provider
        except (ValueError,OSError,requests.RequestException) as exc:
            code=str(exc) if re.fullmatch(r'COVER_[A-Z_0-9]+',str(exc)) else 'COVER_PROVIDER_UNAVAILABLE'
            delay=getattr(exc,'retry_after',600)
            if code in {'COVER_PROVIDER_402','COVER_PROVIDER_NOT_CONFIGURED'}:delay=86400
            with _lock:
                try:state=json.loads(path.read_text())
                except (OSError,ValueError):state={}
                state[name]={'error':code,'retry_after':time.time()+delay}
                path.parent.mkdir(parents=True,exist_ok=True)
                temp=path.with_suffix('.tmp');temp.write_text(json.dumps(state));temp.replace(path)
    return editorial(article)
