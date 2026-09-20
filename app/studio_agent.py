import os, json, re, requests
try:
    from .model_router import model_for
except ImportError:
    from model_router import model_for

def _key():
    return os.environ.get('GEMINI_API_KEY','').strip()

def _model():
    return model_for('reasoning')

def _extract_json(text):
    text = (text or '').strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.I)
        text = re.sub(r'\s*```$', '', text)
    try: return json.loads(text)
    except Exception: pass
    m=re.search(r'\{.*\}', text, re.S)
    if m:
        try: return json.loads(m.group(0))
        except Exception: pass
    return None

def interpret(instruction, mode='image', state=None):
    key=_key()
    if not key:
        return {"ok":False,"error":"No hay GEMINI_API_KEY configurada."}
    allowed_image = [
        'auto_enhance','brightness','contrast','saturation','blur','sharpen','filter','rotate','flip_x','flip_y','zoom',
        'add_text','update_text','delete_text','center_text','set_text_position','set_text_style','preset'
    ]
    allowed_video = [
        'trim_start','trim_end','speed','zoom','rotate','flip_h','flip_v','filter','move_clip','delete_clip','transition',
        'add_text','update_text','delete_text','preset','viral_optimize','generate_music','captions','beat_sync','format'
    ]
    allowed_audio=['volume','fade_in','fade_out','trim','normalize','music_mood','speed']
    actions = allowed_image if mode=='image' else allowed_video if mode=='video' else allowed_audio
    prompt=f'''Eres el intérprete universal de órdenes de Zar Studio. Convierte la orden del usuario en una lista JSON de acciones ejecutables por la interfaz. No respondas con explicaciones: SOLO JSON.\n\nModo: {mode}\nAcciones permitidas: {actions}\nEstado resumido: {json.dumps(state or {}, ensure_ascii=False)[:7000]}\n\nReglas:\n- Comprende español natural, sin exigir palabras concretas.\n- Una orden puede contener varias acciones; devuelve todas en orden.\n- Si el usuario dice "mejora la imagen", usa auto_enhance y ajustes complementarios razonables.\n- "como esta referencia" / "aplica el estilo" usa preset con parámetros generales (tipografía, color, contraste, saturación, ritmo) sin copiar material protegido.\n- Para texto devuelve text, x/y (0..1), font, size, color, opacity, style, rotation cuando proceda.\n- Para video, clip es 1-based.\n- No inventes una capacidad que no esté en la lista. Si no puedes mapear algo, usa action='unsupported' con reason.\n- Devuelve {{"actions":[{{"action":"...",...}}],"summary":"..."}}.\n\nOrden del usuario: {instruction}'''
    url=f'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions'
    payload={"model":_model(),"messages":[{"role":"system","content":"Devuelve únicamente JSON válido."},{"role":"user","content":prompt}],"temperature":0.15}
    try:
        r=requests.post(url,headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},json=payload,timeout=60)
        r.raise_for_status(); data=r.json(); text=((data.get('choices') or [{}])[0].get('message') or {}).get('content','')
        obj=_extract_json(text)
        if not obj or not isinstance(obj.get('actions'),list):
            return {"ok":False,"error":"No pude interpretar la orden de edición."}
        for a in obj['actions']:
            if a.get('action') not in actions and a.get('action')!='unsupported':
                a['action']='unsupported'; a['reason']='Acción no permitida por el editor.'
        return {"ok":True,"actions":obj['actions'],"summary":obj.get('summary','Orden interpretada.')}
    except Exception as exc:
        return {"ok":False,"error":f"No pude interpretar la orden: {exc}"}
