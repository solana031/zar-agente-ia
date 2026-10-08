"""Persistent creative controls on the existing Media job/checkpoint storage."""
import re
import json
from copy import deepcopy
from . import holdings, media_company as media
from .media_adapters import DramaClawAdapter, VoiceAdapter, MediaRenderAdapter

AGENTS = ['StoryAgent','ScriptAgent','CharacterAgent','DirectorAgent','StoryboardAgent','VisualAgent',
          'AnimationAgent','VoiceAgent','AudioAgent','SubtitleAgent','EditorAgent','QAAgent','PublishingAgent']
STAGE_AGENT = {'project':'StoryAgent','configure':'DirectorAgent','upload':'StoryAgent','ingest':'StoryAgent',
    'episodes':'DirectorAgent','characters':'CharacterAgent','identities':'CharacterAgent','portraits':'VisualAgent',
    'identity_images':'VisualAgent','script':'ScriptAgent','colors':'DirectorAgent','storyboard':'StoryboardAgent',
    'detect':'CharacterAgent','optimize':'DirectorAgent','frames':'VisualAgent','narrator':'VoiceAgent',
    'audio':'AudioAgent','videos':'AnimationAgent','compose':'EditorAgent','export':'QAAgent','done':'QAAgent'}


def validate_options(data):
    if not isinstance(data,dict): raise ValueError('Preferencias requeridas.')
    fmt=data.get('format','9:16');style=data.get('visual_style','realistic')
    if fmt not in {'9:16','16:9','1:1'} or style not in {'realistic','anime','chinese_period_drama','post_apocalyptic'}:
        raise ValueError('Formato/estilo no admitido.')
    duration=data.get('duration',60)
    if isinstance(duration,bool) or not isinstance(duration,(int,float)) or not 5 <= duration <= 600:
        raise ValueError('Duración objetivo entre 5 y 600 segundos.')
    for field in ('subtitles','music'):
        if field in data and not isinstance(data[field],bool): raise ValueError('Preferencia booleana requerida.')
    max_scenes=data.get('max_scenes')
    if max_scenes not in (None,''):
        if isinstance(max_scenes,bool) or not str(max_scenes).isdigit() or not 1<=int(max_scenes)<=20:
            raise ValueError('Máximo de escenas entre 1 y 20.')
        max_scenes=int(max_scenes)
    else:max_scenes=None
    return {'title':str(data.get('title') or '')[:150], 'language':str(data.get('language') or 'es')[:30],
        'visual_style':style,'format':fmt,'duration':duration,'subtitles':data.get('subtitles',True),
        'subtitle_language':str(data.get('subtitle_language') or data.get('language') or 'es')[:30],
        'subtitle_style':str(data.get('subtitle_style') or 'default')[:50], 'subtitle_position':'bottom',
        'subtitle_size':24,'music':data.get('music',False), 'duration_is_target':True,
        'max_scenes':max_scenes}


def trace(scope, task_id, record):
    cp=record.get('checkpoint') or {}; stage=cp.get('stage','project')
    agent=STAGE_AGENT.get(stage,'StoryAgent')
    if record.get('status') in {'PUBLISHING','PUBLISHED'}: agent='PublishingAgent'
    event={'timestamp':holdings._now(),'agent':agent,'stage':stage,'state':record.get('status'),
           'provider':'DramaClaw DIRECT','task_ids':[t.get('task_id') for t in cp.get('tasks',[])]}
    rows=record.setdefault('agent_trace',[])
    if not rows or (rows[-1]['stage'],rows[-1]['state']) != (event['stage'],event['state']): rows.append(event)
    with holdings.transaction(scope):
        d=holdings.read(scope);registry=d.setdefault('orchestration',{}).setdefault('agents',{})
        for name in AGENTS:
            registry.setdefault(name,{'id':name,'name':name,'function':'DramaClaw workflow capability','domain':'media',
                'state':'IDLE','capabilities':['workflow_status'],'tools':['workflow_status'],'current_tasks':[],
                'completed_tasks':[],'errors':[],'logs':[],'last_heartbeat':None,'costs':None,'attributed_revenue':None,
                'permissions':['local_read'],'dependencies':[]})
        a=registry[agent];a['last_heartbeat']=event['timestamp'];a['logs']=(a['logs']+[dict(event,project=task_id)])[-100:]
        if a['state'] not in {'PAUSED','OFF'}: a['state']='RUNNING' if record.get('status') in {'PRODUCING','PUBLISHING'} else 'IDLE'
        a['current_tasks']=[task_id] if record.get('status') in {'PRODUCING','PUBLISHING'} else []
        holdings.write(scope,d)


def controls(scope, task_id, action, data):
    task=media._task(scope,task_id)
    with media._job_lock(scope,task_id) as locked:
        if not locked: raise ValueError('Proyecto ocupado; espera a que termine la etapa.')
        record=media._read(scope,task_id)
        cp=record.get('checkpoint') or {}
        if action=='inspect':
            if not cp.get('project_id'): raise ValueError('POR CONFIGURAR / proyecto todavía no creado en DramaClaw.')
            snapshot=DramaClawAdapter(media._client()).inspect(cp)
            assigned={x['name']:x for x in record.get('characters',[])}
            for character in snapshot['characters']:
                old=assigned.get(character['name'],{})
                character.update({k:old.get(k) for k in ('voice','language','provider_reference','voice_preview')})
            record.update(snapshot)
        elif action=='assign_voices':
            result=VoiceAdapter().voices()
            candidates=[v for v in result.get('voices',[]) if v.get('id')]
            if not candidates: raise ValueError('POR CONFIGURAR: proveedor sin candidatos de voz verificados.')
            record['voice_candidates']=candidates
            for index,char in enumerate(record.get('characters',[])):
                if not char.get('voice'):
                    chosen=candidates[index%len(candidates)]
                    char.update(voice=chosen['id'],provider_reference=result['provider'],
                                language=(record.get('project') or {}).get('language','es'),
                                voice_preview=chosen.get('preview_url'),assignment='AUTO_REVIEW_REQUIRED')
            record['audio_needs_render']=True
        elif action=='voice':
            char=next(x for x in record.get('characters',[]) if x['name']==data.get('character'))
            voice=str(data.get('voice') or '')
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,150}',voice): raise ValueError('ID de voz requerido.')
            char.update(voice=voice,language=(record.get('project') or {}).get('language','es'),provider_reference='ElevenLabs',voice_preview=None)
            record['audio_needs_render']=True
        elif action=='character_audio':
            if data.get('confirmed') is not True: raise ValueError('Confirma generación: consume cuota/créditos del proveedor.')
            char=next(x for x in record.get('characters',[]) if x['name']==data.get('character'))
            text=str(data.get('text') or '')
            digest=__import__('hashlib').sha256((char['name']+text+str(char.get('voice'))).encode()).hexdigest()[:20]
            assets=record.setdefault('voice_assets',{})
            if digest in assets: raise ValueError('Audio ya solicitado; se conserva resultado/intención, sin gasto duplicado.')
            assets[digest]={'state':'REQUESTED','character':char['name'],'provider':char.get('provider_reference'),'actual_cost':None}
            media._save(scope,task_id,record)
            try:
                audio,mime,provider=VoiceAdapter().synthesize(text,char.get('voice'),char.get('language') or 'es')
                extension='mp3' if mime in {'audio/mpeg','audio/mp3'} else 'wav' if mime in {'audio/wav','audio/x-wav'} else None
                if not extension: raise ValueError('Formato de audio no compatible.')
                filename=task_id+'-'+digest+'.'+extension
                (media._root(scope)/filename).write_bytes(audio)
                assets[digest].update(state='READY',filename=filename,mime=mime,provider=provider,usage={'characters':len(text)})
                char['voice_preview']='/api/holdings/workflows/media/'+task_id+'/audio/'+digest
                record['audio_needs_render']=True
            except Exception:
                assets[digest]['state']='ERROR'
                media._save(scope,task_id,record)
                raise ValueError('Audio no confirmado; revisa proveedor antes de repetir.') from None
        elif action=='subtitles':
            text=str(data.get('text') or '')
            if len(text)>2*1024*1024: raise ValueError('SRT demasiado grande.')
            if text and not re.search(r'\d\d:\d\d:\d\d[,\.]\d{3}\s+-->\s+\d\d:\d\d:\d\d[,\.]\d{3}',text):
                raise ValueError('Subtítulos requieren tiempos reales en formato SRT; no se inventa sincronización.')
            size=int(data.get('size',24));position=data.get('position','bottom')
            if not 10<=size<=72 or position not in {'top','bottom','middle'}: raise ValueError('Preferencias de subtítulo inválidas.')
            style=data.get('style') or 'default'
            if style not in {'default','boxed','high_contrast'}:raise ValueError('Estilo permitido: default, boxed, high_contrast.')
            record['subtitles']={'text':text,'language':str(data.get('language') or 'es')[:30],
                'enabled':data.get('enabled',True) is True,'style':style,
                'position':position,'size':size,'source':'user_edit','burned_into_video':False}
            record.update(needs_final_render=True,review_approved=False)
        elif action=='render_final':
            path=media.video_path(scope,task_id)
            if record.get('status')!='PRODUCED': raise ValueError('Render requiere vídeo producido.')
            subtitles=record.get('subtitles')
            if not subtitles: raise ValueError('Recupera o guarda primero el SRT y sus preferencias.')
            if cp.get('project_config',{}).get('add_subtitles',True):
                raise ValueError('La fuente DramaClaw ya contiene subtítulos incrustados. Desactívalos en el editor y regenera una fuente limpia antes del render local.')
            previous=record.get('subtitle_render') or {}
            source_path=media._root(scope)/previous['clean_source'] if previous.get('clean_source') else None
            rendered=MediaRenderAdapter().render(path,subtitles,source_path=source_path)
            record.setdefault('renders',[]).append(dict(rendered,timestamp=holdings._now(),preferences=deepcopy(subtitles)))
            record['subtitle_render']=rendered
            subtitles['burned_into_video']=rendered['burned_into_video']
            record.update(needs_final_render=False,review_approved=False)
        elif action=='clean_source':
            if data.get('confirmed') is not True:raise ValueError('Confirma recomposición; puede consumir cuota del proveedor.')
            if record.get('status') not in {'PRODUCED','PUBLISHED'}:raise ValueError('Espera al vídeo producido.')
            cp.setdefault('project_config',{})['add_subtitles']=False
            cp.update(stage='compose',status='running',force_compose=True)
            cp['tasks']=[t for t in cp.get('tasks',[]) if t.get('task_type')!='compose_episode']
            media.archive_render(scope,task_id,record)
            record.pop('artifact',None)
            record.update(checkpoint=cp,status='PRODUCING',review_approved=False,needs_final_render=True)
            holdings.set_company_state(scope,'media','start')
        elif action=='load_subtitles':
            client=media._client()
            if cp.get('stage')!='done': raise ValueError('Esperar exportación para recuperar SRT sincronizado de DramaClaw.')
            response=client.session.get(client.base_url+'/api/v1'+client._episode(cp)+'/export/srt',
                headers=client.headers,timeout=(5,30),allow_redirects=False)
            if not response.ok or len(response.content)>2*1024*1024: raise ValueError('DramaClaw no confirmó subtítulos.')
            text=response.content.decode('utf-8-sig')
            if text and not re.search(r'\d\d:\d\d:\d\d,\d{3}\s+-->',text): raise ValueError('SRT de proveedor no válido.')
            record['subtitles']={'text':text,'source':'DramaClaw DIRECT','language':(record.get('project') or {}).get('subtitle_language','es'),
                'enabled':True,'style':'default','position':'bottom','size':24,'burned_into_video':cp.get('project_config',{}).get('add_subtitles',True)}
        elif action=='ready':
            media.video_path(scope,task_id)
            if record.get('status')!='PRODUCED': raise ValueError('Revisión requiere vídeo producido.')
            if data.get('confirmed') is not True: raise ValueError('Confirma revisión de vídeo.')
            if record.get('audio_needs_render'): raise ValueError('Las voces editadas son assets: importa/verifica su montaje en DramaClaw antes de aprobar el vídeo.')
            if record.get('needs_final_render'): raise ValueError('Renderiza las preferencias editadas antes de aprobar.')
            record['review_approved']=True
        elif action=='voice_import_review':
            if data.get('confirmed') is not True: raise ValueError('Confirma que revisaste/importaste los assets de voz en el editor del proveedor.')
            record['audio_needs_render']=False
            record['manual_voice_import_reviewed_at']=holdings._now()
        elif action=='regenerate_scene':
            if data.get('confirmed') is not True: raise ValueError('Confirma regeneración; puede consumir créditos del proveedor.')
            if record.get('status') in {'PRODUCING','PUBLISHING'}: raise ValueError('Proyecto en ejecución.')
            scene=int(data.get('scene'))
            record.setdefault('history',[]).append(deepcopy(cp))
            def persist(value): record['checkpoint']=value;media._save(scope,task_id,record)
            cp=DramaClawAdapter(media._client()).regenerate_scene(cp,scene,persist)
            record.update(checkpoint=cp,status='PRODUCING',review_approved=False)
            record.pop('artifact',None)
            media.archive_render(scope,task_id,record)
            holdings.set_company_state(scope,'media','start')
        else: raise ValueError('Control no disponible en el contrato conectado.')
        media._save(scope,task_id,record);media._mirror(scope,task,record)
        return media._result(task,record)
