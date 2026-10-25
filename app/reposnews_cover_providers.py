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
INTERNAL = 'ReposNews/internal-editorial-canvas-v1'


class ProviderError(ValueError):
    def __init__(self, code, retry_after=None):
        super().__init__(code)
        try:
            delay = int(retry_after)
        except (ValueError, TypeError):
            try: delay = parsedate_to_datetime(retry_after).timestamp() - time.time()
            except (ValueError, TypeError, OverflowError): delay = 600
        self.retry_after = max(600, min(86400, delay))


def editorial(article):
    """Abstract topic illustration, never a fabricated screenshot, logo or AI claim."""
    seed = hashlib.sha256((str(article.get('repo',''))+'|'+str(article.get('category',''))).encode()).digest()
    im = Image.new('RGB', (1280,720)); draw = ImageDraw.Draw(im)
    for y in range(720):
        draw.line((0,y,1280,y), fill=(12+y//30,35+y//25,31+y//45))
    lime = (177+seed[0]%50,211,109); ivory=(235,238,218)
    for x in range(48,1280,64):
        for y in range(40,720,64): draw.ellipse((x,y,x+2,y+2),fill=(62,87,68))
    subject = ' '.join(str(article.get(k,'')) for k in ('repo','category','title_en','summary_en')).casefold()
    draw.rounded_rectangle((135,125,1145,595), radius=42, outline=(72,105,78),width=3)
    if any(w in subject for w in ('video','audio','reel','media','clip')):
        for n in range(38):
            h=35+seed[n%32]*.65
            x=245+n*21; draw.rounded_rectangle((x,360-h,x+9,360+h),radius=4,fill=lime if n%3 else ivory)
        draw.polygon([(535,265),(535,455),(720,360)],fill=(24,52,42),outline=ivory,width=6)
    elif any(w in subject for w in ('code','sdk','python','developer','api','github')):
        draw.line([(420,235),(285,360),(420,485)],fill=ivory,width=16)
        draw.line([(860,235),(995,360),(860,485)],fill=ivory,width=16)
        draw.line([(700,205),(580,515)],fill=lime,width=20)
        for n in range(7): draw.ellipse((510+n*40,555,516+n*40,561),fill=lime)
    else:
        nodes=[(310,260),(640,215),(970,285),(400,490),(790,480)]
        for a,b in ((0,1),(1,2),(0,3),(1,4),(2,4),(3,4)):
            draw.line([nodes[a],nodes[b]],fill=(94,130,91),width=5)
        for n,(x,y) in enumerate(nodes):
            r=33+seed[n]%24;draw.ellipse((x-r,y-r,x+r,y+r),fill=(26,58,42),outline=lime if n%2 else ivory,width=7)
    draw.line((135,635,1145,635),fill=lime,width=4)
    blob=io.BytesIO();im.save(blob,format='PNG',optimize=True)
    return blob.getvalue(), INTERNAL


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
