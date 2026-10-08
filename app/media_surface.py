"""Direct, scoped Media controls; reuse the existing persisted provider workflow."""
import hashlib
import json
from . import holdings, media_company as media
from .media_projects import validate_options

def generate(scope, data):
    story=str(data.get('story') or '')
    if not story.strip() or len(story)>100000: raise ValueError('Historia requerida, máximo 100.000 caracteres.')
    platform=data.get('platform','tiktok')
    if platform not in {'tiktok','instagram','youtube_shorts','youtube'}: raise ValueError('Plataforma no admitida.')
    options=validate_options(data)
    digest=hashlib.sha256(json.dumps([story,platform,options],sort_keys=True).encode()).hexdigest()
    with holdings.transaction(scope):
        tasks=holdings.read(scope)['companies']['media'].get('queue',[])
        task=next((t for t in reversed(tasks) if t.get('payload',{}).get('generation_key')==digest),None)
        if not task:
            active=next((t for t in tasks if media._read(scope,t['id']).get('status')=='PRODUCING'),None)
            if active: raise ValueError('Ya hay una producción activa. Ver progreso o pausar antes de crear otra.')
            task=media.queue_story(scope,story,platform=platform,options=options)
            task['payload']['generation_key']=digest
            record=media._read(scope,task['id']);record['payload']=task['payload']
            media._save(scope,task['id'],record);media._mirror(scope,task,record)
    return media.produce_local(scope,task['id'])

def edit(scope, data):
    task_id=data.get('task_id');task=media._task(scope,task_id)
    options=validate_options(data)
    story=str(data.get('story') or task['payload'].get('master_brief') or '')
    if len(story)>100000: raise ValueError('Historia demasiado larga.')
    spec={k:str(data.get(k) or '')[:30000] for k in ('script','scenes','characters','voices','subtitle_text')}
    with media._job_lock(scope,task_id) as locked:
        if not locked: raise ValueError('Etapa activa; espera antes de editar.')
        record=media._read(scope,task_id);cp=record.get('checkpoint',{})
        if record.get('status') in {'PRODUCING','PUBLISHING'} or cp.get('pending') or cp.get('active_task') or cp.get('active_tasks'):
            raise ValueError('Resuelve la tarea activa antes de editar; se conservan sus IDs.')
        if record.get('checkpoint'):
            record.setdefault('history',[]).append(cp)
            media.archive_render(scope,task_id,record)
            record.pop('artifact',None)
        record.update(project=options,editor_spec=spec,checkpoint={},status='QUEUED',review_approved=False,error=None)
        brief=story+'\n\nEDICIÓN ZAR:\n'+json.dumps(spec,ensure_ascii=False) if any(spec.values()) else story
        record['payload']={**task['payload'],'master_brief':brief,'topic':brief,'editor_story':story}
        record['payload'].pop('generation_key',None)
        media._save(scope,task_id,record);media._mirror(scope,task,record)
    return {'ok':True,'task_id':task_id,'status':'QUEUED'}

def pause(scope, task_id):
    task=media._task(scope,task_id)
    with media._job_lock(scope,task_id) as locked:
        if not locked: raise ValueError('Etapa activa; vuelve a pausar cuando termine la petición actual.')
        record=media._read(scope,task_id)
        if record.get('status')=='PUBLISHING': raise ValueError('Una publicación enviada no puede cancelarse desde ZAR.')
        record.update(status='PAUSED',error='Avance ZAR pausado. Las tareas ya aceptadas por DramaClaw pueden continuar; reintentar consulta los mismos IDs.')
        media._save(scope,task_id,record);media._mirror(scope,task,record)
    return {'ok':True,'status':'PAUSED','task_id':task_id}

def retry_stage(scope, task_id):
    """Explicit retry of a definitively failed stage; preserve earlier outputs and IDs."""
    task=media._task(scope,task_id)
    if holdings.read(scope).get('global_stop'):raise ValueError('STOP GLOBAL activo; reanúdalo antes de producir.')
    with media._job_lock(scope,task_id) as locked:
        if not locked: raise ValueError('Etapa activa; espera antes de reintentar.')
        record=media._read(scope,task_id);cp=record.get('checkpoint') or {}
        if cp.get('pending') or cp.get('active_tasks'): raise ValueError('Resuelve el envío pendiente antes de reintentar; no se duplicará.')
        active=cp.get('active_task')
        if not active or active.get('status') not in {'failed','cancelled'}: raise ValueError('Solo se puede reintentar una etapa con fallo confirmado.')
        capabilities=media._client().capabilities()
        if not capabilities.get('configured'): raise ValueError('ACTION_REQUIRED: configura Model Gateway en dramaclaw-api antes de reintentar.')
        record.setdefault('history',[]).append(json.loads(json.dumps(cp)))
        cp.pop('active_task');cp.pop('error',None);cp.pop('error_code',None)
        cp.update(status='running',submission_state='PROCESSING')
        record.update(status='PRODUCING',error=None)
        media._save(scope,task_id,record);media._mirror(scope,task,record)
        holdings.set_company_state(scope,'media','start')
    return {'ok':True,'task_id':task_id,'stage':cp['stage'],'status':'PRODUCING'}

def subtitles(scope, data):
    task_id=data.get('task_id');task=media._task(scope,task_id)
    with media._job_lock(scope,task_id) as locked:
        if not locked: raise ValueError('Producción activa; espera antes de editar subtítulos.')
        record=media._read(scope,task_id)
        text=data.get('text')
        if text is None:
            client=media._client();cp=record.get('checkpoint') or {}
            if not cp.get('project_id'): raise ValueError('Sin proyecto con subtítulos disponibles.')
            response=client.session.get(client.base_url+'/api/v1'+client._episode(cp)+'/export/srt',headers=client.headers,timeout=(5,20),allow_redirects=False)
            if not response.ok or 'json' in response.headers.get('Content-Type',''): raise ValueError('DramaClaw todavía no confirmó SRT real.')
            text=response.text
        if not isinstance(text,str) or len(text)>500000 or not text.strip(): raise ValueError('SRT requerido, máximo 500.000 caracteres.')
        import re
        if not re.search(r'\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}',text): raise ValueError('SRT sin marcas de tiempo válidas.')
        path=media._path(scope,task_id).with_suffix('.srt');path.write_text(text,encoding='utf-8')
        record['subtitles']={'style':'default','position':'bottom','size':24,**(record.get('subtitles') or {}),'text':text,'enabled':data.get('enabled',True) is True,'file':path.name,'source':'provider' if data.get('text') is None else 'edited','render_pending':True}
        if data.get('text') is not None:record['needs_final_render']=True
        record['review_approved']=False
        media._save(scope,task_id,record);media._mirror(scope,task,record)
    return {'ok':True,'url':'/api/holdings/media/subtitles/'+task_id,'render_pending':True}

def thumbnail(scope, data):
    """Capture a real frame from the scoped durable MP4; no provider generation."""
    import math,shutil,subprocess
    task_id=data.get('task_id');task=media._task(scope,task_id)
    timestamp=float(data.get('timestamp',0))
    if not math.isfinite(timestamp) or not 0<=timestamp<=600:raise ValueError('Tiempo del frame fuera de límites.')
    binary=shutil.which('ffmpeg')
    if not binary:raise ValueError('FFmpeg no disponible para extraer portada.')
    with media._job_lock(scope,task_id) as locked:
        if not locked:raise ValueError('Producción activa; espera antes de extraer portada.')
        source=media.video_path(scope,task_id);path=media._path(scope,task_id).with_suffix('.jpg')
        result=subprocess.run([binary,'-y','-ss',str(timestamp),'-i',str(source),'-frames:v','1','-update','1',str(path)],capture_output=True,timeout=30)
        if result.returncode or not path.is_file():raise ValueError('No se pudo confirmar un frame real del vídeo.')
        record=media._read(scope,task_id);record['thumbnail']={'file':path.name,'source':'video_frame','timestamp':timestamp,'created_at':holdings._now()}
        media._save(scope,task_id,record);media._mirror(scope,task,record)
    return {'ok':True,'url':'/api/holdings/media/thumbnail/'+task_id}
