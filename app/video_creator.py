import json, os, re, shutil, subprocess, threading, uuid, wave, math, random
from pathlib import Path
from datetime import datetime, timezone

try:
    from imageio_ffmpeg import get_ffmpeg_exe
except Exception:
    get_ffmpeg_exe = None

DATA_DIR = Path(os.environ.get('ZAR_DATA_DIR','/data'))
VIDEO_DIR = DATA_DIR / 'video_creator'
PROJECTS_DIR = VIDEO_DIR / 'projects'
MEDIA_DIR = VIDEO_DIR / 'media'
MUSIC_DIR = VIDEO_DIR / 'music'
OUTPUT_DIR = VIDEO_DIR / 'outputs'
for p in (PROJECTS_DIR, MEDIA_DIR, MUSIC_DIR, OUTPUT_DIR): p.mkdir(parents=True, exist_ok=True)
LOCK = threading.RLock()
MAX_VIDEO_UPLOAD = int(os.environ.get('ZAR_VIDEO_MAX_UPLOAD_MB','2048')) * 1024 * 1024

PRESETS = {
    'youtube': {'label':'YouTube 16:9','w':1920,'h':1080,'fps':30},
    'shorts': {'label':'YouTube Shorts 9:16','w':1080,'h':1920,'fps':30},
    'tiktok': {'label':'TikTok 9:16','w':1080,'h':1920,'fps':30},
    'square': {'label':'Cuadrado 1:1','w':1080,'h':1080,'fps':30},
}
MOODS = {
    'cinematic': {'bpm':92,'root':55,'name':'Cinemático'},
    'energetic': {'bpm':124,'root':65,'name':'Energético'},
    'chill': {'bpm':78,'root':57,'name':'Chill'},
    'dramatic': {'bpm':82,'root':49,'name':'Dramático'},
    'travel': {'bpm':108,'root':60,'name':'Viaje'},
}

# Built on FFmpeg xfade: 58 transition modes available in current bundled FFmpeg.
# We expose them in friendly groups so the editor can offer a large professional-style library
# without requiring third-party plugins.
TRANSITIONS = [
    ('básicas', [('fade','Disolución'),('dissolve','Dissolve'),('fadeblack','Fundido a negro'),('fadewhite','Fundido a blanco'),('fadefast','Fundido rápido'),('fadeslow','Fundido lento'),('fadegrays','Fundido a grises'),('none','Corte limpio')]),
    ('barridos', [('wipeleft','Barrido izquierda'),('wiperight','Barrido derecha'),('wipeup','Barrido arriba'),('wipedown','Barrido abajo'),('wipetl','Barrido diagonal ↖'),('wipetr','Barrido diagonal ↗'),('wipebl','Barrido diagonal ↙'),('wipebr','Barrido diagonal ↘'),('coverleft','Cobertura izquierda'),('coverright','Cobertura derecha'),('coverup','Cobertura arriba'),('coverdown','Cobertura abajo'),('revealleft','Revelado izquierda'),('revealright','Revelado derecha'),('revealup','Revelado arriba'),('revealdown','Revelado abajo')]),
    ('deslizamientos', [('slideleft','Deslizamiento izquierda'),('slideright','Deslizamiento derecha'),('slideup','Deslizamiento arriba'),('slidedown','Deslizamiento abajo'),('squeezeh','Compresión horizontal'),('squeezev','Compresión vertical')]),
    ('formas', [('circleopen','Círculo abrir'),('circleclose','Círculo cerrar'),('circlecrop','Recorte circular'),('rectcrop','Recorte rectangular'),('radial','Radial'),('vertopen','Apertura vertical'),('vertclose','Cierre vertical'),('horzopen','Apertura horizontal'),('horzclose','Cierre horizontal'),('diagtl','Diagonal ↖'),('diagtr','Diagonal ↗'),('diagbl','Diagonal ↙'),('diagbr','Diagonal ↘')]),
    ('zoom y movimiento', [('zoomin','Zoom in'),('distance','Distancia'),('smoothleft','Movimiento suave izquierda'),('smoothright','Movimiento suave derecha'),('smoothup','Movimiento suave arriba'),('smoothdown','Movimiento suave abajo'),('hlwind','Viento horizontal izquierda'),('hrwind','Viento horizontal derecha'),('vuwind','Viento vertical arriba'),('vdwind','Viento vertical abajo')]),
    ('dinámicas', [('pixelize','Pixelizado'),('hblur','Desenfoque horizontal'),('hlslice','Corte horizontal izquierda'),('hrslice','Corte horizontal derecha'),('vuslice','Corte vertical arriba'),('vdslice','Corte vertical abajo')]),
]
TRANSITION_META = {key: {'key': key, 'label': label, 'group': group} for group, items in TRANSITIONS for key, label in items}
TRANSITION_KEYS = set(TRANSITION_META)

FILTERS = {
    'none': 'Normal',
    'cinematic': 'Cinemático',
    'warm': 'Cálido',
    'cool': 'Frío',
    'vivid': 'Vívido',
    'bw': 'Blanco y negro',
    'vintage': 'Vintage',
}

def ffmpeg():
    if not get_ffmpeg_exe:
        raise RuntimeError('Falta imageio-ffmpeg. Instala las dependencias de Zar.')
    return get_ffmpeg_exe()

def safe_name(name):
    name = Path(name or 'media').name
    return re.sub(r'[^\w.()\- áéíóúüñÁÉÍÓÚÜÑ]+','_',name)[:180] or 'media'

def now_iso(): return datetime.now(timezone.utc).isoformat()

def save_project(p):
    tmp = Path(str(p['_path'])+'.tmp')
    tmp.write_text(json.dumps({k:v for k,v in p.items() if k!='_path'}, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(p['_path'])

def project_path(pid): return PROJECTS_DIR / f'{pid}.json'
def output_path(pid): return OUTPUT_DIR / f'{pid}.mp4'

def list_projects():
    out=[]
    for f in sorted(PROJECTS_DIR.glob('*.json'), key=lambda x:x.stat().st_mtime, reverse=True):
        try:
            p=json.loads(f.read_text(encoding='utf-8')); p['_path']=str(f); out.append({k:v for k,v in p.items() if k!='_path'})
        except Exception: pass
    return out

def _normalize_media_item(item, idx):
    item.setdefault('order', idx)
    item.setdefault('trim_start', 0.0)
    item.setdefault('trim_end', None)
    item.setdefault('speed', 1.0)
    item.setdefault('volume', 1.0)
    item.setdefault('zoom', 1.0)
    item.setdefault('pan_x', 0.0)
    item.setdefault('pan_y', 0.0)
    item.setdefault('rotate', 0)
    item.setdefault('flip_h', False)
    item.setdefault('flip_v', False)
    item.setdefault('filter', 'none')
    item.setdefault('caption', '')
    item.setdefault('caption_position', 'bottom')
    item.setdefault('segment_effects', [])
    item.setdefault('text_overlays', [])
    item.setdefault('transition_to_next', 'crossfade')
    item.setdefault('transition_duration', 0.45)
    return item

def create_project(name='', preset='youtube', music_mood='cinematic', transition='crossfade', image_duration=3.2):
    # V27 compatibility: map old "crossfade" to FFmpeg's fade mode.
    transition = 'fade' if transition == 'crossfade' else transition
    if transition not in TRANSITION_KEYS: transition = 'fade'
    pid=uuid.uuid4().hex
    p={
        'id':pid,'name':(name or 'Proyecto sin título').strip()[:120],
        'preset':preset if preset in PRESETS else 'youtube',
        'music_mood':music_mood if music_mood in MOODS else 'cinematic',
        'transition':transition,
        'image_duration':max(1.0,min(float(image_duration or 3.2),10.0)),
        'media':[],'music':None,
        'editor': {'quality':'balanced','auto_caption':False,'viral_mode':False,'beat_sync':False,'title':'','description':''},
        'created_at':now_iso(),'updated_at':now_iso()
    }
    p['_path']=str(project_path(pid)); save_project(p); return {k:v for k,v in p.items() if k!='_path'}

def get_project(pid):
    f=project_path(pid)
    if not f.exists(): return None
    try:
        p=json.loads(f.read_text(encoding='utf-8')); p['_path']=str(f)
        changed=False
        if 'media' in p:
            for i,it in enumerate(p['media']):
                before=dict(it); _normalize_media_item(it,i); changed |= before != it
        if 'editor' not in p: p['editor']={'quality':'balanced','auto_caption':False,'viral_mode':False,'beat_sync':False,'title':'','description':''}; changed=True
        if changed: save_project(p)
        return p
    except Exception:return None

def set_project(pid, patch):
    p=get_project(pid)
    if not p: raise ValueError('Proyecto no encontrado.')
    if not isinstance(patch, dict): raise ValueError('Configuración inválida.')
    allowed={'name','preset','music_mood','transition','image_duration','editor'}
    for k,v in patch.items():
        if k not in allowed: continue
        if k=='preset' and v not in PRESETS: continue
        if k=='transition':
            v='fade' if v=='crossfade' else v
            if v not in TRANSITION_KEYS: continue
        if k=='image_duration': v=max(1.0,min(float(v),10.0))
        if k=='music_mood' and v not in MOODS: continue
        if k=='editor' and isinstance(v,dict):
            p['editor'].update(v); continue
        p[k]=v
    p['updated_at']=now_iso(); save_project(p); return {k:v for k,v in p.items() if k!='_path'}

def add_media(pid, file_storage):
    p=get_project(pid)
    if not p: raise ValueError('Proyecto no encontrado.')
    if not file_storage or not file_storage.filename: raise ValueError('No se recibió el archivo.')
    mime=file_storage.mimetype or ''
    ext=Path(file_storage.filename).suffix.lower()
    allowed_img={'.jpg','.jpeg','.png','.webp','.bmp','.gif'}
    allowed_vid={'.mp4','.mov','.m4v','.webm','.avi','.mkv'}
    if not (mime.startswith('image/') or mime.startswith('video/') or ext in allowed_img or ext in allowed_vid): raise ValueError('Solo se admiten fotos y vídeos.')
    data=file_storage.read()
    if len(data)>MAX_VIDEO_UPLOAD: raise ValueError(f'El archivo supera el límite de {MAX_VIDEO_UPLOAD//(1024*1024)} MB.')
    mid=uuid.uuid4().hex; name=safe_name(file_storage.filename); stored=f'{mid}{ext or ".bin"}'; path=MEDIA_DIR/stored; path.write_bytes(data)
    kind='image' if (mime.startswith('image/') or ext in allowed_img) else 'video'
    item={'id':mid,'name':name,'stored_name':stored,'kind':kind,'mime':mime,'size':len(data),'duration':None}
    _normalize_media_item(item, len(p['media']))
    p['media'].append(item); p['updated_at']=now_iso(); save_project(p); return item

def media_path(item): return MEDIA_DIR / item['stored_name']

def delete_media(pid, media_index):
    p=get_project(pid)
    if not p: raise ValueError('Proyecto no encontrado.')
    idx=int(media_index)
    if idx<1 or idx>len(p['media']): raise ValueError('Índice de clip fuera de rango.')
    item=p['media'].pop(idx-1)
    try: media_path(item).unlink(missing_ok=True)
    except Exception: pass
    p['updated_at']=now_iso(); save_project(p); return {k:v for k,v in p.items() if k!='_path'}

def move_media(pid, old_index, new_index):
    p=get_project(pid)
    if not p: raise ValueError('Proyecto no encontrado.')
    n=len(p['media']); a=int(old_index); b=int(new_index)
    if not (1<=a<=n and 1<=b<=n): raise ValueError('Índice de clip fuera de rango.')
    item=p['media'].pop(a-1); p['media'].insert(b-1,item)
    for i,it in enumerate(p['media']): it['order']=i
    p['updated_at']=now_iso(); save_project(p); return {k:v for k,v in p.items() if k!='_path'}

def update_media(pid, index, patch):
    p=get_project(pid)
    if not p: raise ValueError('Proyecto no encontrado.')
    i=int(index)-1
    if i<0 or i>=len(p['media']): raise ValueError('Índice de clip fuera de rango.')
    it=_normalize_media_item(p['media'][i], i)
    for k,v in (patch or {}).items():
        if k not in {'trim_start','trim_end','speed','volume','zoom','pan_x','pan_y','rotate','flip_h','flip_v','filter','caption','caption_position','transition_to_next','transition_duration'}: continue
        if k in {'trim_start','speed','volume','zoom','pan_x','pan_y','transition_duration'}: v=float(v)
        if k=='trim_end' and v not in (None,'','null'): v=float(v)
        if k=='rotate': v=int(v)%360
        if k=='filter' and v not in FILTERS: v='none'
        if k=='transition_to_next': v='fade' if v=='crossfade' else v; v=v if v in TRANSITION_KEYS else 'fade'
        if k=='transition_duration': v=max(0.05,min(v,2.0))
        it[k]=v
    p['updated_at']=now_iso(); save_project(p); return {k:v for k,v in p.items() if k!='_path'}


def _normalize_text_overlay(data):
    import uuid as _uuid
    d = dict(data or {})
    d.setdefault('id', _uuid.uuid4().hex[:12])
    d.setdefault('text', 'Texto')
    d.setdefault('x', 0.5)
    d.setdefault('y', 0.5)
    d.setdefault('font', 'DejaVu Sans')
    d.setdefault('size', 54)
    d.setdefault('color', '#ffffff')
    d.setdefault('opacity', 1.0)
    d.setdefault('stroke', 0)
    d.setdefault('stroke_color', '#000000')
    d.setdefault('shadow', True)
    d.setdefault('rotation', 0)
    d.setdefault('style', 'normal')
    d.setdefault('start', 0.0)
    d.setdefault('end', None)
    d['x'] = max(0.0, min(1.0, float(d.get('x', 0.5))))
    d['y'] = max(0.0, min(1.0, float(d.get('y', 0.5))))
    d['size'] = max(10, min(240, int(float(d.get('size', 54)))))
    d['opacity'] = max(0.0, min(1.0, float(d.get('opacity', 1.0))))
    d['stroke'] = max(0, min(12, int(float(d.get('stroke', 0)))))
    d['rotation'] = float(d.get('rotation', 0) or 0)
    d['start'] = max(0.0, float(d.get('start', 0) or 0))
    end = d.get('end')
    d['end'] = None if end in (None, '', 'null') else max(d['start'], float(end))
    d['color'] = str(d.get('color') or '#ffffff')
    d['stroke_color'] = str(d.get('stroke_color') or '#000000')
    d['font'] = str(d.get('font') or 'DejaVu Sans')
    d['style'] = str(d.get('style') or 'normal')
    d['shadow'] = bool(d.get('shadow', True))
    d['text'] = str(d.get('text') or '')[:500]
    return d


def add_text_overlay(pid, index, data):
    p=get_project(pid)
    if not p: raise ValueError('Proyecto no encontrado.')
    i=int(index)-1
    if i<0 or i>=len(p.get('media',[])): raise ValueError('Índice de clip fuera de rango.')
    _normalize_media_item(p['media'][i], i)
    ov=_normalize_text_overlay(data)
    p['media'][i].setdefault('text_overlays', []).append(ov)
    p['updated_at']=now_iso(); save_project(p)
    return {k:v for k,v in p.items() if k!='_path'}


def update_text_overlay(pid, index, overlay_id, patch):
    p=get_project(pid)
    if not p: raise ValueError('Proyecto no encontrado.')
    i=int(index)-1
    if i<0 or i>=len(p.get('media',[])): raise ValueError('Índice de clip fuera de rango.')
    _normalize_media_item(p['media'][i], i)
    overlays=p['media'][i].setdefault('text_overlays', [])
    ov=next((x for x in overlays if str(x.get('id'))==str(overlay_id)), None)
    if ov is None: raise ValueError('Texto no encontrado.')
    allowed={'text','x','y','font','size','color','opacity','stroke','stroke_color','shadow','rotation','style','start','end'}
    for k,v in (patch or {}).items():
        if k not in allowed: continue
        ov[k]=v
    ov.update(_normalize_text_overlay(ov))
    p['updated_at']=now_iso(); save_project(p)
    return {k:v for k,v in p.items() if k!='_path'}


def delete_text_overlay(pid, index, overlay_id):
    p=get_project(pid)
    if not p: raise ValueError('Proyecto no encontrado.')
    i=int(index)-1
    if i<0 or i>=len(p.get('media',[])): raise ValueError('Índice de clip fuera de rango.')
    overlays=p['media'][i].setdefault('text_overlays', [])
    p['media'][i]['text_overlays']=[x for x in overlays if str(x.get('id'))!=str(overlay_id)]
    p['updated_at']=now_iso(); save_project(p)
    return {k:v for k,v in p.items() if k!='_path'}


def _fontfile_for(font_name):
    import subprocess as _subprocess
    mapping={
        'sans':'DejaVu Sans','serif':'DejaVu Serif','mono':'DejaVu Sans Mono','condensed':'DejaVu Sans Condensed',
        'liberation sans':'Liberation Sans','liberation serif':'Liberation Serif','liberation mono':'Liberation Mono',
        'noto sans':'Noto Sans','noto serif':'Noto Serif','arimo':'Arimo'
    }
    fam=mapping.get(str(font_name or '').strip().lower(), str(font_name or 'DejaVu Sans'))
    try:
        r=_subprocess.run(['fc-match','-f','%{file}',fam],capture_output=True,text=True,timeout=8)
        path=(r.stdout or '').strip()
        return path if path and Path(path).exists() else ''
    except Exception:
        return ''


def _ffmpeg_escape_text(text):
    return str(text or '').replace('\\','\\\\').replace(':','\\:').replace("'","\\'").replace('[','\\[').replace(']','\\]')


def _hex_to_ffmpeg(hex_color, alpha=1.0):
    c=str(hex_color or '#ffffff').strip().lstrip('#')
    if len(c) not in (6,8): c='ffffff'
    if len(c)==8:
        a=int(c[6:8],16)/255.0
        c=c[:6]
        alpha*=a
    try: a=max(0,min(1,float(alpha)))
    except Exception: a=1.0
    return '#'+c+f'@{a:.3f}'


def _text_overlay_filter(overlay, w, h):
    text=_ffmpeg_escape_text(overlay.get('text',''))
    if not text: return ''
    fontfile=_fontfile_for(overlay.get('font','DejaVu Sans'))
    fontsize=max(10,min(240,int(overlay.get('size',54) or 54)))
    color=_hex_to_ffmpeg(overlay.get('color','#ffffff'), overlay.get('opacity',1))
    sc=_hex_to_ffmpeg(overlay.get('stroke_color','#000000'), .9)
    sw=max(0,min(12,int(overlay.get('stroke',0) or 0)))
    x=f"({w}*{max(0,min(1,float(overlay.get('x',.5))))}-text_w/2)"
    y=f"({h}*{max(0,min(1,float(overlay.get('y',.5))))}-text_h/2)"
    start=max(0,float(overlay.get('start',0) or 0))
    end=overlay.get('end')
    enable=f":enable='gte(t,{start})'"
    if end not in (None,'',0): enable=f":enable='between(t,{start},{float(end)})'"
    parts=[f"drawtext=text='{text}'", f"fontcolor={color}", f"fontsize={fontsize}", f"x={x}", f"y={y}", f"rotation={float(overlay.get('rotation',0) or 0)*3.14159265/180:.8f}", f"borderw={sw}", f"bordercolor={sc}"]
    if fontfile:
        ff = fontfile.replace('\\', '/').replace("'", "\\'")
        parts.append("fontfile='" + ff + "'")
    style=str(overlay.get('style','normal'))
    if style=='box':
        parts += ['box=1','boxcolor=#000000@0.42','boxborderw=14']
    elif style in ('shadow','glow') or overlay.get('shadow'):
        parts += ['shadowcolor=#000000@0.65','shadowx=3','shadowy=3']
    return ':'.join(parts)+enable


def _text_overlay_filters(item, w, h):
    out=[]
    for ov in item.get('text_overlays') or []:
        try:
            f=_text_overlay_filter(_normalize_text_overlay(ov),w,h)
            if f: out.append(f)
        except Exception:
            continue
    return out

def generate_music(project_id, mood='cinematic', duration=30, seed=None):
    if mood not in MOODS: mood='cinematic'
    duration=max(5,min(int(duration or 30),600))
    seed=int(seed or int(uuid.uuid4().hex[:8],16)); rng=random.Random(seed)
    meta=MOODS[mood]; bpm=meta['bpm']; beat=60.0/bpm; sr=44100; n=int(duration*sr)
    wav_path=MUSIC_DIR/f'{project_id}_{mood}_{seed}.wav'
    chords=[[0,4,7],[5,9,0],[7,11,2],[0,4,7]]
    buf=bytearray()
    for i in range(n):
        t=i/sr; beat_idx=int(t/beat); bar=beat_idx//4; phase=2*math.pi*t
        root=meta['root']*2**((bar*5)%12/12)
        bassf=root*2**(chords[bar%4][0]/12)
        bass=0.11*math.sin(phase*bassf)
        pad=sum(math.sin(phase*(root*2**(sem/12)) + math.sin(t*.4)*.08)*.032 for sem in chords[bar%4])
        leadf=root*2**(((beat_idx//2)+bar)%7/12)*2
        lead=.024*math.sin(phase*leadf)*(0.5+0.5*math.sin(t*.9))
        kick=snare=hat=0.0; bt=t%beat
        if bt<.09: kick=.17*math.exp(-32*bt)*math.sin(2*math.pi*(70-35*(bt/.09))*bt)
        if beat_idx%4 in (1,3) and bt<.12: snare=.075*math.exp(-28*bt)*(2*rng.random()-1)
        if bt<.035: hat=.025*math.exp(-85*bt)*(2*rng.random()-1)
        env=min(1,t/.8,(duration-t)/1.2 if t>duration-1.2 else 1)
        x=max(-.45,min(.45,(bass+pad+lead+kick+snare+hat)*env)); s=int(x*32767); buf += int(s).to_bytes(2,'little',signed=True)*2
    with wave.open(str(wav_path),'wb') as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr); w.writeframes(buf)
    return {'path':str(wav_path),'mood':mood,'mood_label':meta['name'],'bpm':bpm,'duration':duration,'seed':seed,'generated':True,'rights_note':'Pista instrumental original procedural de Zar; no se incluyen canciones ni samples de terceros.'}

def probe_duration(path):
    try:
        r=subprocess.run([ffmpeg(),'-i',str(path),'-hide_banner','-loglevel','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1'],capture_output=True,text=True,timeout=30)
        return float((r.stdout or '0').strip() or 0)
    except Exception:return 0.0

def _filter_for_item(item, w, h, fps):
    parts=[]
    # speed first, then geometric transforms.
    speed=max(0.25,min(float(item.get('speed',1.0) or 1.0),4.0))
    parts.append(f'setpts=PTS/{speed}')
    z=max(1.0,min(float(item.get('zoom',1.0) or 1.0),2.0))
    # modest center zoom; pan nudges crop window.
    crop_w=max(2,int(w/z)); crop_h=max(2,int(h/z))
    px=float(item.get('pan_x',0) or 0); py=float(item.get('pan_y',0) or 0)
    crop_x=f'({w}-{crop_w})/2+({w}-{crop_w})/2*{max(-1,min(1,px))}'
    crop_y=f'({h}-{crop_h})/2+({h}-{crop_h})/2*{max(-1,min(1,py))}'
    parts.append(f'scale={w}:{h}:force_original_aspect_ratio=increase')
    if z>1.001:
        parts.append(f'crop={crop_w}:{crop_h}:{crop_x}:{crop_y}')
        parts.append(f'scale={w}:{h}')
    else:
        parts.append(f'crop={w}:{h}')
    rot=int(item.get('rotate',0) or 0)%360
    if rot==90: parts.append('transpose=1')
    elif rot==180: parts.append('hflip,vflip')
    elif rot==270: parts.append('transpose=2')
    if item.get('flip_h'): parts.append('hflip')
    if item.get('flip_v'): parts.append('vflip')
    # Re-normalize dimensions after rotations/flips so xfade inputs always match.
    if rot in (90,270): parts.append(f'scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}')
    filt=item.get('filter','none')
    if filt=='bw': parts.append('hue=s=0')
    elif filt=='warm': parts.append('eq=saturation=1.08:gamma_r=1.05:gamma_b=.94')
    elif filt=='cool': parts.append('eq=saturation=1.05:gamma_r=.96:gamma_b=1.06')
    elif filt=='vivid': parts.append('eq=contrast=1.08:saturation=1.22')
    elif filt=='cinematic': parts.append('eq=contrast=1.08:saturation=1.05:gamma=.98')
    elif filt=='vintage': parts.append('eq=contrast=.95:saturation=.82:gamma=1.03,curves=vintage')
    parts.append(f'fps={fps}')
    parts.append('format=yuv420p')
    return ','.join(parts)

def _apply_text_filter(item, w, h):
    caption=(item.get('caption') or '').strip()
    if not caption: return ''
    # Avoid external fonts: use default DejaVuSans via libfreetype when available.
    safe=caption.replace('\\','\\\\').replace(':','\\:').replace("'","\\'")
    if item.get('caption_position')=='top': y='40'
    elif item.get('caption_position')=='middle': y='(h-text_h)/2'
    else: y='h-text_h-60'
    return f"drawtext=text='{safe}':fontcolor=white:fontsize={max(28,int(w/38))}:borderw=3:bordercolor=black@0.65:x=(w-text_w)/2:y={y}"

def _segment_filters(item):
    out=[]
    for eff in item.get('segment_effects') or []:
        try: start=float(eff.get('start',0)); end=float(eff.get('end',start+1))
        except Exception: continue
        if end<=start: continue
        enable=f":enable='between(t,{start},{end})'"
        typ=eff.get('type')
        if typ=='bw': out.append('hue=s=0'+enable)
        elif typ=='vivid': out.append('eq=contrast=1.12:saturation=1.25'+enable)
        elif typ=='blur': out.append('boxblur=4:1'+enable)
        elif typ=='warm': out.append('eq=saturation=1.08:gamma_r=1.05:gamma_b=.94'+enable)
        elif typ=='cool': out.append('eq=saturation=1.05:gamma_r=.96:gamma_b=1.06'+enable)
        elif typ=='brightness':
            try: val=float(eff.get('value',0.08))
            except Exception: val=.08
            out.append(f'eq=brightness={max(-1,min(1,val))}'+enable)
    return out

def render_project(pid, music=True):
    p=get_project(pid)
    if not p: raise ValueError('Proyecto no encontrado.')
    if not p.get('media'): raise ValueError('Añade al menos una foto o un vídeo.')
    preset=PRESETS.get(p.get('preset','youtube'),PRESETS['youtube']); fps=preset['fps']; w=preset['w']; h=preset['h']; duration_img=float(p.get('image_duration',3.2))
    work=VIDEO_DIR/f'work_{pid}_{uuid.uuid4().hex}'; work.mkdir(parents=True,exist_ok=True)
    clips=[]
    try:
        ordered=list(p['media'])
        for idx,item in enumerate(ordered):
            src=media_path(item)
            if not src.exists(): continue
            out=work/f'clip_{idx:03d}.mp4'
            filt=_filter_for_item(item,w,h,fps)
            caption_filter=_apply_text_filter(item,w,h)
            if caption_filter: filt += ','+caption_filter
            segment_filters=_segment_filters(item)
            if segment_filters: filt += ','+','.join(segment_filters)
            text_filters=_text_overlay_filters(item,w,h)
            if text_filters: filt += ','+','.join(text_filters)
            start=max(0,float(item.get('trim_start',0) or 0))
            extra=[]
            if item.get('kind')=='image':
                filt2=f'scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},zoompan=z=1:s={w}x{h}:fps={fps}:d={max(1,int(duration_img*fps))}'
                # For image edits, use a simpler deterministic chain to avoid zoompan/fps interactions.
                filt=f'scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps},format=yuv420p'
                if item.get('zoom',1.0)!=1.0 or item.get('pan_x') or item.get('pan_y'):
                    z=max(1,min(2,float(item.get('zoom',1.0) or 1.0))); cw=int(w/z); ch=int(h/z)
                    px=max(-1,min(1,float(item.get('pan_x',0) or 0))); py=max(-1,min(1,float(item.get('pan_y',0) or 0)))
                    cx=int((w-cw)/2+(w-cw)/2*px); cy=int((h-ch)/2+(h-ch)/2*py)
                    filt=f'scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},crop={cw}:{ch}:{cx}:{cy},scale={w}:{h},fps={fps},format=yuv420p'
                # append visual operations after image crop
                visual=_filter_for_item({'speed':1.0,'zoom':1.0,'pan_x':0,'pan_y':0,'rotate':item.get('rotate',0),'flip_h':item.get('flip_h',False),'flip_v':item.get('flip_v',False),'filter':item.get('filter','none')},w,h,fps)
                visual_parts=visual.split(',')
                tail=[x for x in visual_parts if not x.startswith(('setpts=','scale=','crop=','fps=','format='))]
                if tail: filt += ','+','.join(tail)+f',format=yuv420p'
                dur=duration_img
                cmd=[ffmpeg(),'-y','-loop','1','-i',str(src),'-t',str(dur),'-vf',filt,'-an','-c:v','libx264','-preset','veryfast','-crf','22','-movflags','+faststart',str(out)]
            else:
                duration=probe_duration(src)
                end=item.get('trim_end')
                ss=max(0,start); to=None if end in (None,'',0) else max(ss+0.05,float(end))
                cmd=[ffmpeg(),'-y']
                if ss>0: cmd += ['-ss',str(ss)]
                cmd += ['-i',str(src)]
                if to is not None: cmd += ['-t',str(to-ss)]
                cmd += ['-vf',filt,'-an','-c:v','libx264','-preset','veryfast','-crf','22','-movflags','+faststart',str(out)]
            r=subprocess.run(cmd,capture_output=True,text=True,timeout=900)
            if r.returncode!=0: raise RuntimeError('No se pudo procesar '+item.get('name','el archivo')+'\n'+(r.stderr[-1200:] if r.stderr else ''))
            clips.append(out)
        if not clips: raise ValueError('No hay medios válidos en el proyecto.')
        video_only=work/'video.mp4'
        if len(clips)==1:
            r=subprocess.run([ffmpeg(),'-y','-i',str(clips[0]),'-c:v','copy','-movflags','+faststart',str(video_only)],capture_output=True,text=True,timeout=900)
        else:
            durations=[max(probe_duration(c),0.5) for c in clips]
            filters=[]; current='[0:v]'; offset=durations[0]-max(.05,min(2,float(ordered[0].get('transition_duration',.45) or .45)))
            for i in range(1,len(clips)):
                prev_item=ordered[i-1]
                trans=prev_item.get('transition_to_next') or p.get('transition','fade')
                trans='fade' if trans=='crossfade' else trans
                if trans=='none':
                    # Concatenation is not expressible with xfade: fall back to a cut via concat filter after normalizing durations.
                    trans='fade'
                    tdur=0.001
                else:
                    tdur=max(.05,min(2,float(prev_item.get('transition_duration',.45) or .45)))
                nxt=f'[v{i}]'
                filters.append(f'{current}[{i}:v]xfade=transition={trans}:duration={tdur}:offset={max(0,offset)}{nxt}')
                current=nxt
                offset += durations[i]-tdur
            filters.append(f'{current}format=yuv420p[vout]')
            cmd=[ffmpeg(),'-y']
            for c in clips: cmd += ['-i',str(c)]
            cmd += ['-filter_complex',';'.join(filters),'-map','[vout]','-r',str(fps),'-c:v','libx264','-preset','veryfast','-crf','22','-movflags','+faststart',str(video_only)]
            r=subprocess.run(cmd,capture_output=True,text=True,timeout=1200)
        if r.returncode!=0: raise RuntimeError('No se pudo unir el vídeo. '+(r.stderr[-1400:] if r.stderr else ''))
        final=output_path(pid)
        music_path=None; music_meta=None
        if music:
            total=max(5,sum(probe_duration(x) for x in clips))
            music_meta=generate_music(pid,p.get('music_mood','cinematic'),int(math.ceil(total)))
            music_path=music_meta['path']
        if music_path:
            cmd=[ffmpeg(),'-y','-i',str(video_only),'-stream_loop','-1','-i',str(music_path),'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k','-shortest','-movflags','+faststart',str(final)]
        else:
            cmd=[ffmpeg(),'-y','-i',str(video_only),'-c:v','copy','-movflags','+faststart',str(final)]
        r=subprocess.run(cmd,capture_output=True,text=True,timeout=1200)
        if r.returncode!=0: raise RuntimeError('No se pudo generar la exportación. '+(r.stderr[-1200:] if r.stderr else ''))
        p['music']=music_meta; p['output']={'path':str(final),'url':f'/api/video/projects/{pid}/preview','size':final.stat().st_size,'created_at':now_iso()}
        p['updated_at']=now_iso(); save_project(p)
        return {'ok':True,'project':{k:v for k,v in p.items() if k!='_path'},'preview_url':f'/api/video/projects/{pid}/preview','download_url':f'/api/video/projects/{pid}/download'}
    finally:
        shutil.rmtree(work,ignore_errors=True)

def transition_catalog():
    return [{'group':group,'items':[{'key':k,'label':label} for k,label in items]} for group,items in TRANSITIONS]

def viral_optimize(pid, platform='shorts'):
    p=get_project(pid)
    if not p: raise ValueError('Proyecto no encontrado.')
    platform=(platform or 'shorts').lower()
    if platform in ('tiktok','reels','shorts','youtube_shorts'): preset='tiktok' if platform=='tiktok' else 'shorts'
    else: preset='youtube'
    p['preset']=preset
    p['editor']['viral_mode']=True
    p['editor']['beat_sync']=True
    # Heuristic optimization rather than a claim of guaranteed virality.
    p['image_duration']=min(float(p.get('image_duration',3.2)),1.8)
    fast=['fade','zoomin','smoothleft','smoothright','slideleft','slideright','radial','pixelize']
    for i,it in enumerate(p.get('media',[])):
        _normalize_media_item(it,i)
        it['transition_to_next']=fast[i%len(fast)]
        it['transition_duration']=0.25 if i%3 else 0.35
        if i<2: it['zoom']=max(float(it.get('zoom',1.0)),1.08)
    p['updated_at']=now_iso(); save_project(p)
    return {'ok':True,'project':{k:v for k,v in p.items() if k!='_path'},'strategy':{
        'approach':'Optimización heurística para vídeo corto: apertura rápida, ritmo de cortes, movimiento suave, formato vertical y texto/gancho temprano.',
        'not_guarantee':'No garantiza viralidad; usa señales públicas y debe validarse con las métricas reales de tu cuenta.'
    }}

def _num(text):
    return float(str(text).replace(',','.'))

def apply_edit_command(pid, instruction):
    """Interpreta órdenes naturales frecuentes y las convierte en cambios no destructivos de proyecto.
    La operación solo cambia el JSON del proyecto; el original se conserva.
    """
    p=get_project(pid)
    if not p: raise ValueError('Proyecto no encontrado.')
    text=re.sub(r'\s+',' ',(instruction or '').strip().lower())
    if not text: raise ValueError('Escribe una orden de edición.')
    actions=[]

    m=re.search(r'(?:quita|elimina|borra)\s+(?:el\s+)?(?:clip|vídeo|video|archivo)\s*(\d+)',text)
    if m:
        p=delete_media(pid,int(m.group(1))); actions.append(f'he eliminado el clip {m.group(1)}')
        return {'ok':True,'project':p,'actions':actions}
    m=re.search(r'(?:mueve|pon)\s+(?:el\s+)?(?:clip|vídeo|video)\s*(\d+)\s+(?:al|a la)\s+(?:principio|inicio|final|fin)',text)
    if m:
        src=int(m.group(1)); dest=1 if 'principio' in text or 'inicio' in text else len(p['media']); p=move_media(pid,src,dest); actions.append(f'he movido el clip {src}')
        return {'ok':True,'project':p,'actions':actions}
    m=re.search(r'(?:mueve|pon)\s+(?:el\s+)?(?:clip|vídeo|video)\s*(\d+)\s+(?:a|después de|detrás de)\s+(?:el\s+)?(?:clip|vídeo|video)?\s*(\d+)',text)
    if m:
        src=int(m.group(1)); ref=int(m.group(2)); dest=min(ref+1,len(p['media'])); p=move_media(pid,src,dest); actions.append(f'he recolocado el clip {src}')
        return {'ok':True,'project':p,'actions':actions}
    m=re.search(r'(?:recorta|corta|quita)\s+(?:los\s+)?primeros?\s*([\d.,]+)\s*(?:s|segundos?)\s+(?:del\s+)?(?:clip|vídeo|video)\s*(\d+)',text)
    if m:
        sec=_num(m.group(1)); idx=int(m.group(2)); p=update_media(pid,idx,{'trim_start':sec}); actions.append(f'he recortado {sec:.2f}s del inicio del clip {idx}')
        return {'ok':True,'project':p,'actions':actions}
    m=re.search(r'(?:deja|haz)\s+(?:el\s+)?(?:clip|vídeo|video)\s*(\d+)\s+(?:en|a)\s*([\d.,]+)\s*(?:s|segundos?)',text)
    if m:
        sec=_num(m.group(2)); idx=int(m.group(1)); p=update_media(pid,idx,{'trim_start':0,'trim_end':sec}); actions.append(f'he dejado el clip {idx} en {sec:.2f}s')
        return {'ok':True,'project':p,'actions':actions}
    m=re.search(r'(?:más rápido|mas rapido|acelera|acelerar)\s+(?:el\s+)?(?:clip|vídeo|video)\s*(\d+)(?:\s+(?:a|al)\s*([\d.,]+)\s*x)?',text)
    if m:
        idx=int(m.group(1)); factor=_num(m.group(2)) if m.group(2) else 1.35; p=update_media(pid,idx,{'speed':factor}); actions.append(f'he acelerado el clip {idx} a {factor:.2f}x')
        return {'ok':True,'project':p,'actions':actions}
    m=re.search(r'(?:más lento|mas lento|ralentiza|ralentizar)\s+(?:el\s+)?(?:clip|vídeo|video)\s*(\d+)(?:\s+(?:a|al)\s*([\d.,]+)\s*x)?',text)
    if m:
        idx=int(m.group(1)); factor=_num(m.group(2)) if m.group(2) else .75; p=update_media(pid,idx,{'speed':factor}); actions.append(f'he ralentizado el clip {idx} a {factor:.2f}x')
        return {'ok':True,'project':p,'actions':actions}
    m=re.search(r'(?:haz|pon)\s+(?:zoom|un zoom)\s*(?:de|x)?\s*([\d.,]+)?\s*x?\s*(?:en\s+el\s+)?(?:clip|vídeo|video)\s*(\d+)',text)
    if m:
        factor=_num(m.group(1)) if m.group(1) else 1.12; idx=int(m.group(2)); p=update_media(pid,idx,{'zoom':factor}); actions.append(f'he aplicado zoom {factor:.2f}x al clip {idx}')
        return {'ok':True,'project':p,'actions':actions}
    m=re.search(r'(?:gira|rota)\s+(?:el\s+)?(?:clip|vídeo|video)\s*(\d+)\s*(?:\s*(?:a|de)\s*)?([\d.,]+)\s*(?:grados|º|°)',text)
    if m:
        idx=int(m.group(1)); deg=int(_num(m.group(2))); p=update_media(pid,idx,{'rotate':deg}); actions.append(f'he rotado el clip {idx} {deg}°')
        return {'ok':True,'project':p,'actions':actions}
    m=re.search(r'(?:voltea|invierte)\s+(?:horizontalmente\s+)?(?:el\s+)?(?:clip|vídeo|video)\s*(\d+)',text)
    if m:
        idx=int(m.group(1)); p=update_media(pid,idx,{'flip_h':True}); actions.append(f'he volteado horizontalmente el clip {idx}')
        return {'ok':True,'project':p,'actions':actions}
    m=re.search(r'(?:pon|usa|utiliza|cambia|aplica)\s+(.+?)\s+(?:entre|del)\s+(?:los\s+)?clips?\s*(\d+)\s+(?:y|al)\s+(?:clip\s*)?(\d+)',text)
    if not m:
        m=re.search(r'(?:transición|transicion)\s+(?:entre|del)\s+(?:clip\s*)?(\d+)\s+(?:y|al)\s+(?:clip\s*)?(\d+)\s+(?:en|a|con)\s+(.+)$',text)
        if m:
            # normalize groups for the common branch below
            a=int(m.group(1)); b=int(m.group(2)); name=m.group(3).strip()
        else:
            a=b=name=None
    else:
        name=m.group(1).strip(); a=int(m.group(2)); b=int(m.group(3))
        # fall through to transition matching
    if a is not None:
        matches=[k for k,v in TRANSITION_META.items() if name==v['label'].lower() or name==k or name in v['label'].lower()]
        if not matches: raise ValueError('No reconozco esa transición. Abre la biblioteca de transiciones para ver las disponibles.')
        p=update_media(pid,a,{'transition_to_next':matches[0]}); actions.append(f'he puesto {TRANSITION_META[matches[0]]["label"]} entre los clips {a} y {b}')
        return {'ok':True,'project':p,'actions':actions}
    m=re.search(r'(?:pon|usa|utiliza)\s+(?:una\s+)?transición\s+(?:suave|rápida|rapida|aleatoria|random)',text)
    if m:
        choices=['fade','smoothleft','smoothright','slideleft','slideright'];
        for i,it in enumerate(p.get('media',[])[:-1]): it['transition_to_next']=choices[i%len(choices)]; it['transition_duration']=.28 if 'rápida' in text or 'rapida' in text else .45
        p['updated_at']=now_iso(); save_project(p); actions.append('he aplicado una secuencia de transiciones equilibradas')
        return {'ok':True,'project':{k:v for k,v in p.items() if k!='_path'},'actions':actions}
    m=re.search(r'(?:añade|anade|agrega|pon|crea)\s+(?:un\s+)?(?:texto|título|titulo)\s+(?:en\s+)?(?:el\s+)?(?:clip\s*)?(\d+)\s*[:\-]?\s*[«"“]?(.+?)[»"”]?\s*(?:en\s+(arriba|abajo|centro|izquierda|derecha))?$',text)
    if m:
        idx=int(m.group(1)); caption=m.group(2).strip(' \t\"“”«»'); pos=(m.group(3) or 'centro').lower()
        xy={'centro':(.5,.5),'arriba':(.5,.16),'abajo':(.5,.86),'izquierda':(.16,.5),'derecha':(.84,.5)}[pos]
        p=add_text_overlay(pid,idx,{'text':caption,'x':xy[0],'y':xy[1],'style':'shadow','shadow':True})
        actions.append(f'he añadido el texto al clip {idx}')
        return {'ok':True,'project':p,'actions':actions}

    m=re.search(r'(?:mueve|coloca|pon)\s+(?:el\s+)?texto(?:\s+del\s+clip\s*(\d+))?\s+(?:a|en)\s+(arriba|abajo|centro|izquierda|derecha)',text)
    if m:
        idx=int(m.group(1) or 1); pos=m.group(2).lower(); p=get_project(pid); overlays=(p['media'][idx-1].get('text_overlays') or []) if 0<idx<=len(p.get('media',[])) else []
        if not overlays: raise ValueError(f'El clip {idx} no tiene un texto superpuesto.')
        xy={'centro':(.5,.5),'arriba':(.5,.16),'abajo':(.5,.86),'izquierda':(.16,.5),'derecha':(.84,.5)}[pos]
        p=update_text_overlay(pid,idx,overlays[-1]['id'],{'x':xy[0],'y':xy[1]}); actions.append(f'he movido el último texto del clip {idx}')
        return {'ok':True,'project':p,'actions':actions}

    m=re.search(r'(?:haz|pon)\s+(?:el\s+)?texto(?:\s+del\s+clip\s*(\d+))?\s+(?:en\s+)?(negrita|outline|contorno|caja|cuadro|sombra|brillo|glow)',text)
    if m:
        idx=int(m.group(1) or 1); effect=m.group(2); p=get_project(pid); overlays=(p['media'][idx-1].get('text_overlays') or []) if 0<idx<=len(p.get('media',[])) else []
        if not overlays: raise ValueError(f'El clip {idx} no tiene un texto superpuesto.')
        ov=overlays[-1]; patch={}
        if effect=='negrita': patch['font']='DejaVu Sans'; patch['size']=max(int(ov.get('size',54)),60)
        elif effect in ('outline','contorno'): patch['style']='outline'; patch['stroke']=4
        elif effect in ('caja','cuadro'): patch['style']='box'
        elif effect=='sombra': patch['style']='shadow'; patch['shadow']=True
        elif effect in ('brillo','glow'): patch['style']='glow'; patch['shadow']=True
        p=update_text_overlay(pid,idx,ov['id'],patch); actions.append(f'he aplicado {effect} al texto del clip {idx}')
        return {'ok':True,'project':p,'actions':actions}

    m=re.search(r'(?:texto|título|titulo)\s+(?:en\s+)?(?:el\s+)?(?:clip\s*)?(\d+)\s*[:\-]?\s*(.+)$',text)
    if m:
        idx=int(m.group(1)); caption=m.group(2).strip(' "“”'); p=update_media(pid,idx,{'caption':caption}); actions.append(f'he añadido texto al clip {idx}')
        return {'ok':True,'project':p,'actions':actions}
    m=re.search(r'(?:quita|elimina)\s+el\s+texto\s+(?:del\s+)?(?:clip\s*)?(\d+)',text)
    if m:
        idx=int(m.group(1)); p=update_media(pid,idx,{'caption':''}); actions.append(f'he quitado el texto del clip {idx}')
        return {'ok':True,'project':p,'actions':actions}
    if any(x in text for x in ('optimiza para viral','hazlo más viral','hazlo mas viral','optimiza la viralidad','modo viral')):
        platform='tiktok' if 'tiktok' in text else 'shorts' if ('short' in text or 'reel' in text) else 'shorts'
        return viral_optimize(pid,platform)
    m=re.search(r'(?:entre|del)\s*([\d.,]+)\s*(?:y|a)\s*([\d.,]+)\s*(?:segundos?|s)\s+(?:del\s+)?(?:clip|vídeo|video)\s*(\d+)\s+(?:pon|aplica|haz)\s+(blanco y negro|desenfoque|blur|más contraste|mas contraste|más brillo|mas brillo|tono cálido|tono calido|tono frío|tono frio)',text)
    if m:
        start=_num(m.group(1)); end=_num(m.group(2)); idx=int(m.group(3)); desc=m.group(4)
        typ='bw' if 'blanco' in desc else 'blur' if ('blur' in desc or 'desenfoque' in desc) else 'vivid' if 'contraste' in desc else 'brightness' if 'brillo' in desc else 'warm' if 'cálido' in desc or 'calido' in desc else 'cool'
        p=get_project(pid); i=idx-1
        if i<0 or i>=len(p['media']): raise ValueError('Índice de clip fuera de rango.')
        _normalize_media_item(p['media'][i],i); p['media'][i].setdefault('segment_effects',[]).append({'start':start,'end':end,'type':typ})
        p['updated_at']=now_iso(); save_project(p); actions.append(f'he aplicado {desc} solo entre {start:g}s y {end:g}s del clip {idx}')
        return {'ok':True,'project':{k:v for k,v in p.items() if k!='_path'},'actions':actions}

    if any(x in text for x in ('más cálido','mas calido','tono cálido','tono calido')):
        for i in range(1,len(p['media'])+1): p=update_media(pid,i,{'filter':'warm'})
        actions.append('he aplicado un look cálido al montaje')
    elif any(x in text for x in ('más frío','mas frio','tono frío','tono frio')):
        for i in range(1,len(p['media'])+1): p=update_media(pid,i,{'filter':'cool'})
        actions.append('he aplicado un look frío al montaje')
    elif any(x in text for x in ('blanco y negro','en blanco y negro')):
        for i in range(1,len(p['media'])+1): p=update_media(pid,i,{'filter':'bw'})
        actions.append('he aplicado blanco y negro al montaje')
    elif any(x in text for x in ('más vivo','mas vivo','más contraste','mas contraste')):
        for i in range(1,len(p['media'])+1): p=update_media(pid,i,{'filter':'vivid'})
        actions.append('he reforzado color y contraste del montaje')
    else:
        raise ValueError('No he identificado una operación concreta. Prueba con órdenes como «recorta el clip 3 a 2 segundos», «haz zoom 1.15x en el clip 2», «pon zoom in entre 2 y 3», «añade el texto 1: VERANO» o «optimiza para viral en TikTok».')
    return {'ok':True,'project':{k:v for k,v in p.items() if k!='_path'},'actions':actions}
