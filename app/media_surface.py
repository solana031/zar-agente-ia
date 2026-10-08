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
