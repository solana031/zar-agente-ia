"""Node chat uses a scoped Cloud gateway; provider credentials never leave Cloud."""
import json
import os
from pathlib import Path
import re
import threading
import time
import unicodedata
from urllib.parse import urlparse
import uuid

import requests
from .scoped_http import BearerAuth

ROOT = Path(__file__).resolve().parents[1]
_LOCK = threading.Lock()
_LAST = {}


def enabled():
    return os.environ.get('ZAR_NODE_CHAT') == '1' and not os.environ.get('RAILWAY_ENVIRONMENT')


def context():
    from .node_worker import Worker, capabilities, resources, WORKER_VERSION
    worker = Worker()
    with worker.connect() as con:
        row = con.execute('SELECT payload FROM heartbeat WHERE id=1').fetchone()
    beat = json.loads(row['payload']) if row else {}
    fresh = 0 <= time.time()-beat.get('timestamp',0) < 15
    return {**worker.identity(), 'capabilities':beat.get('capabilities',[]) if fresh else capabilities(),
            'resources':beat.get('resources',{}) if fresh else resources(),
            'version':(ROOT/'VERSION').read_text().strip(), 'worker_version':WORKER_VERSION}


def transport():
    base = os.environ.get('ZAR_CLOUD_URL','').strip().rstrip('/')
    token = os.environ.get('ZAR_NODE_TOKEN','').strip()
    if not base or not token:
        return None, None, 'DEGRADED', 'Gateway/enrolamiento Cloud no configurados.'
    url = urlparse(base)
    if url.scheme!='https' or not url.hostname or url.username or url.password or url.path or url.query or url.fragment or not 32<=len(token)<=256:
        return None, None, 'DEGRADED', 'Configuración del gateway no válida: requiere un origen HTTPS y token individual.'
    return base, token, 'NOT_VERIFIED', 'Conexión Cloud todavía no verificada.'


def status():
    _,_,state,reason = transport()
    with _LOCK:
        last = dict(_LAST)
    if state=='DEGRADED':
        return {'state':state,'reason':reason,'model':None,'provider':None}
    return last or {'state':state,'reason':reason,'model':None,'provider':None}


def record(state,reason,model=None,provider=None):
    with _LOCK:
        _LAST.update(state=state,reason=reason,model=model,provider=provider)


def identity_question(message):
    text = ''.join(c for c in unicodedata.normalize('NFKD',message.lower()) if not unicodedata.combining(c))
    if len(text)>350 or re.search(r'\b(programa|escribe|calcula|publica|compra|envia|ejecuta|genera|traduce|resume|analiza)\b',text):
        return False
    return bool(re.search(r'en (?:que|cual) nodo|donde (?:te )?(?:estas|ejecut)|capacidades locales|tus capacidades',text))


def local_identity(node):
    current = status()
    resource = node['resources']
    ram = resource.get('ram_bytes')
    answer = (f"La sesión de ZAR se ejecuta en {node['name']} (node_id: {node['id']}).\n"
              f"Capacidades locales detectadas: {', '.join(node['capabilities'])}.\n"
              f"Sistema: {resource.get('os','—')} / {resource.get('architecture','—')}; "
              f"CPU: {resource.get('cpu_count','—')}; RAM: {round(ram/1073741824,1) if ram else '—'} GiB.\n"
              f"Cloud: {current['state']}. {current['reason']}\n"
              'Datos obtenidos localmente, no generados por un modelo. La inferencia general se delega a ZAR Cloud cuando está conectado.')
    from .smart_router import BrainRoute, remember_decision
    remember_decision(BrainRoute('node-status','local-status','none','Identidad y capacidades reales; sin LLM'))
    return answer


def respond(message, cfg):
    node = context()
    is_identity = identity_question(message)
    base,token,state,reason = transport()
    if is_identity and not base:
        return local_identity(node)
    if base:
        if token in message:
            state,reason = 'DEGRADED','No se envían credenciales en el texto de inferencia.'
        elif len(message)>6000:
            state,reason = 'DEGRADED','Esta ruta admite como máximo 6000 caracteres por petición.'
        else:
            try:
                response = requests.post(base+'/v1/nodes/inference',
                    headers={'Authorization':'Bearer '+token},auth=BearerAuth(token),
                    json={'request_id':str(uuid.uuid4()),'heartbeat':{'id':node['id']},'prompt':message},
                    timeout=(5,75),allow_redirects=False)
                if response.status_code==200:
                    data = response.json()
                    text = data.get('text')
                    if data.get('state')!='ONLINE' or not isinstance(text,str) or not text.strip() or len(text)>12000:
                        raise ValueError('Invalid gateway response')
                    text = text.replace(token,'[REDACTED]')
                    provider,model = data.get('provider'),data.get('model')
                    if (not isinstance(model,str) or not re.fullmatch(r'[A-Za-z0-9._:/-]{1,120}',model)
                            or token in model or provider not in {'gemini','openai','openrouter'}
                            or data.get('node_id',node['id'])!=node['id']
                            or set(data)-{'state','text','model','provider','node_id'}):
                        raise ValueError('Invalid model metadata')
                    record('ONLINE','Inferencia autenticada mediante ZAR Cloud.',model,provider)
                    facts = local_identity(node)+'\n\n' if is_identity else ''
                    from .smart_router import BrainRoute, remember_decision
                    remember_decision(BrainRoute('cloud','cloud-gateway',model,'Inferencia saliente del nodo'),provider,model)
                    return facts+f"{node['name']} · inferencia ZAR Cloud ({provider} / {model})\n\n{text}"
                state = 'OFFLINE' if response.status_code in {502,504} else 'DEGRADED'
                reason = ({401:'Token del nodo no válido.',403:'Nodo revocado, pausado o sin permiso de inferencia.',
                           429:'Límite de inferencia del nodo alcanzado.',503:'Gateway deshabilitado o proveedor no disponible.'}
                          .get(response.status_code,'Gateway no disponible; no se ha seguido ninguna redirección.'))
            except requests.RequestException:
                state,reason = 'OFFLINE','No se pudo conectar de forma segura con ZAR Cloud.'
            except (ValueError,TypeError,KeyError):
                state,reason = 'DEGRADED','El gateway devolvió una respuesta no válida.'
    record(state,reason)
    if is_identity:
        return local_identity(node)
    if os.environ.get('ZAR_NODE_LOCAL_FALLBACK')=='1':
        from .smart_router import local_available, BrainRoute, remember_decision
        if local_available(cfg):
            from .agent import local_text
            try:
                answer = local_text('Datos locales verificados: '+json.dumps(node,ensure_ascii=False)+'\nUsuario: '+message,cfg)
                model = cfg['local']['model']
                record(state,reason+' Fallback Ollama local disponible.',model,'local')
                remember_decision(BrainRoute('local','local',model,'Fallback Ollama explícitamente habilitado'))
                return f"{node['name']} · Cloud {state}; fallback local Ollama ({model})\n\n{answer}"
            except Exception:
                reason += ' El fallback local tampoco está disponible.'
    return f"{node['name']} · {state}\n{reason}\nNo hay un modelo de inferencia disponible para esta petición."
