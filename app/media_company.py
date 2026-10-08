"""Persistent Media workflow on the existing Holdings worker; DramaClaw only."""
from __future__ import annotations

import hashlib
import json
import re
import os
import secrets
import requests
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import holdings
from .dramaclaw_client import DramaClawClient, DramaClawError
from .social_publish import status as social_status, tiktok_direct_post, instagram_reel
from .user_scope import safe_slug

_LABELS = {"project": "creando proyecto", "create": "creando proyecto", "upload": "ingiriendo historia", "episodes": "planificando episodio", "videos": "vídeo", "narrator": "voz", "ingest": "ingiriendo historia", "script": "guion",
           "storyboard": "storyboard", "video": "vídeo", "voice": "voz", "audio": "voz",
           "compose": "composición", "done": "terminado"}
_HEALTH = {}


def _client():
    base = os.environ.get("DRAMACLAW_API_URL", "").strip()
    if not base:
        raise ValueError("DramaClaw no conectado: configura DRAMACLAW_API_URL y sus modelos.")
    return DramaClawClient(base, token=os.environ.get("DRAMACLAW_API_TOKEN", ""),
                          public_url=os.environ.get("DRAMACLAW_WEB_URL", ""))


def status():
    # Bounded, short-lived cache: refresh never launches generation or model calls.
    key = hashlib.sha256((os.environ.get("DRAMACLAW_API_URL", "") + "|" +
                          os.environ.get("DRAMACLAW_API_TOKEN", "")).encode()).hexdigest()
    cached = _HEALTH.get(key)
    if not cached or time.monotonic() - cached[0] > 30:
        try:
            client = _client()
            check = client.health()
            if check.get('ready'):
                try:
                    check['capabilities'] = client.capabilities()
                except DramaClawError:
                    check['capabilities'] = {'configured': False, 'provider': 'UNKNOWN', 'missing_requirement': 'Verificar configuración del gateway', 'service': 'dramaclaw-api'}
        except Exception:
            check = {"ready": False, "error": "DramaClaw no disponible; revisa URL, acceso y modelos."}
        _HEALTH.clear()
        _HEALTH[key] = (time.monotonic(), check)
    check = _HEALTH[key][1]
    ready = bool(check.get("ready"))
    configured = bool(os.environ.get("DRAMACLAW_API_URL", "").strip())
    return {"ready": ready, "api_ready": ready, "generation_ready": False, "capabilities": check.get('capabilities', {}), "label": "DramaClaw CORE · LISTO · generación por verificar" if ready else "DramaClaw DIRECT · NO DISPONIBLE",
            "error": check.get("error") if not ready else None, "message": check.get("message"),
            "dramaclaw_direct_configured": configured, "dramaclaw_bridge_configured": configured,
            "direct_only": True, "visual_fallback": "desactivado", "attribution_required": True,
            "preferred_provider": "DramaClaw Direct", "social": social_status()}


def _root(scope_id):
    root = Path(os.environ.get("ZAR_DATA_DIR", "/data")) / "users" / safe_slug(scope_id) / "media_jobs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _path(scope_id, task_id):
    if not task_id or not str(task_id).isalnum() or len(str(task_id)) > 64:
        raise ValueError("Identificador Media inválido.")
    return _root(scope_id) / (str(task_id) + ".json")


@contextmanager
def _job_lock(scope_id, task_id):
    """One worker/request per job, also across Gunicorn processes; crash releases it."""
    path = _path(scope_id, task_id).with_suffix(".lock")
    with path.open("a+b") as handle:
        handle.seek(0, 2)
        if not handle.tell():
            handle.write(b"0"); handle.flush()
        handle.seek(0)
        acquired = False
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except (OSError, BlockingIOError):
            pass
        try:
            yield acquired
        finally:
            if acquired:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)


def _read(scope_id, task_id):
    path = _path(scope_id, task_id)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _save(scope_id, task_id, record):
    from .relayclaw_cost_tracker import RelayClawCostTracker
    record['costs']=RelayClawCostTracker.record(task_id,record)
    cp = record.get('checkpoint') or {}
    status = record.get('status')
    stage = cp.get('stage')
    phase = 'DRAFT'
    if status == 'PRODUCING':
        phase = 'SCRIPTING'
        if stage in {'storyboard','detect','colors','optimize'}: phase='STORYBOARD'
        elif stage in {'portraits','identity_images','frames','videos'}: phase='GENERATING_VISUALS'
        elif stage in {'narrator','audio'}: phase='GENERATING_AUDIO'
        elif stage in {'compose','export','done'}: phase='EDITING'
    elif status=='PRODUCED': phase='READY' if record.get('review_approved') else 'REVIEW'
    elif status=='PUBLISHED': phase='PUBLISHED'
    elif status=='PUBLISHING': phase='READY'
    elif status=='ERROR': phase='ERROR'
    record['project_state']=phase
    record.setdefault('costs',{'estimated':None,'actual':None,'currency':None,'provider':'DramaClaw DIRECT','usage':None})
    from .media_projects import trace
    trace(scope_id, task_id, record)
    path = _path(scope_id, task_id)
    temp = path.with_suffix("." + secrets.token_hex(6) + ".tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False)
            handle.flush(); os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _task(scope_id, task_id):
    task = next((t for t in holdings.read(scope_id)["companies"]["media"].get("queue", [])
                 if t["id"] == task_id), None)
    if not task:
        raise ValueError("Tarea Media no encontrada.")
    return task


def _result(task, record):
    cp = record.get("checkpoint") or {}
    stage = cp.get("stage", "create")
    result = {"stage": stage, "stage_label": _LABELS.get(stage, stage), "progress": cp.get("progress", 0),
              "project_id": cp.get("project_id"), "task_ids": cp.get("tasks", cp.get("task_records", [])),
              "editor_url": cp.get("editor_url") if os.environ.get("DRAMACLAW_WEB_URL", "").strip() else None, "production_provider": "DramaClaw Direct",
              "brief_chars": len((record.get("payload") or task.get("payload") or {}).get("master_brief", "")),
              "caption": "Creado con DramaClaw · #historia #reels #tiktok", "aigc": True, "format": (record.get('project') or {}).get('format','9:16'),
              "project_state":record.get('project_state','DRAFT'), "project":record.get('project'),
              "characters":record.get('characters',[]),"scenes":record.get('scenes',[]),"script":record.get('script'),
              "subtitles":record.get('subtitles'),"costs":record.get('costs'),"agent_trace":record.get('agent_trace',[]),
              "rendered_at":record.get('rendered_at'),"renders":record.get('renders',[]),"publications":record.get('publications',[])}
    result.update(submission_state=('READY' if record.get('artifact') else 'UNKNOWN' if cp.get('error_code') in {'submission_unknown','task_missing','task_status'} else 'FAILED' if cp.get('status')=='blocked' else cp.get('submission_state') or 'PROCESSING'), editor_spec=record.get('editor_spec',{}), error_code=cp.get('error_code'), submission_error=cp.get('last_submission_error'),
                  submission_message=cp.get('submission_message'), active_tasks=cp.get('active_tasks') or ([cp['active_task']] if cp.get('active_task') else []))
    from .dramaclaw_client import STAGES
    index = STAGES.index(stage) if stage in STAGES else 0
    result['pipeline'] = [{'stage': name, 'status': 'READY' if i < index or cp.get('status') == 'done' else 'FAILED' if i == index and cp.get('status') == 'blocked' else 'RUNNING' if i == index and record.get('status') == 'PRODUCING' else 'PENDING'} for i, name in enumerate(STAGES) if name != 'done']
    result['diagnostic'] = {'provider': 'DramaClawAPI' if 'DramaClawAPI' in str(cp.get('error')) else 'DramaClaw', 'stage': stage, 'error': cp.get('error'), 'missing_requirement': 'Model Gateway credential (dramaclaw-api)' if 'credenciales' in str(cp.get('error')) else None}
    if 'insufficient_user_quota' in str(cp.get('error')):
        result['diagnostic'].update(provider='RelayClaw',missing_requirement='Saldo de cuenta RelayClaw',action_required='Activar crédito personalmente; no repetir generación sin saldo.')
    if record.get("artifact"):
        result['file_size'] = record.get('file_size')
        result["preview_url"] = "/api/holdings/media/video/" + task["id"]
        result["download_url"] = result["preview_url"]
    if record.get('thumbnail'):result['thumbnail_url']='/api/holdings/media/thumbnail/'+task['id']
    if any(r.get("source")=="previous_revision" for r in record.get("renders",[])):
        result["previous_preview_url"]="/api/holdings/media/video/"+task["id"]+"?revision=previous"
    if record.get("publish"):
        result["publish"] = record["publish"]
    return result


def _mirror(scope_id, task, record):
    holdings.update_task(scope_id, "media", task["id"], status=record.get("status", "QUEUED"),
                         result=_result(task, record), payload=record.get("payload", task["payload"]),
                         error=record.get("error"))


def jobs(scope_id):
    state = holdings.read(scope_id)
    tasks = state["companies"]["media"].get("queue", [])
    for task in tasks:
        record = _read(scope_id, task["id"])
        if record:
            task.update(status=record.get("status", task["status"]), error=record.get("error"),
                        payload=record.get("payload", task.get("payload")), result=_result(task, record))
    connector = status()
    caps = state.get('identity_center',{}).get('capabilities',{})
    connector['publication_states'] = {name.lower(): 'CONNECTED' if caps.get(name,{}).get('status') == 'CONNECTED' else 'ACTION_REQUIRED' for name in ('YOUTUBE','INSTAGRAM','TIKTOK')}
    return {"ok": True, "tasks": tasks[-30:], "connector": connector}


def queue_story(scope_id, topic, goal="retención", platform="tiktok", *, options=None):
    master_brief = str(topic or "")
    if not master_brief.strip():
        raise ValueError("Falta la historia/briefing.")
    project = None
    if options is not None:
        from .media_projects import validate_options
        project = validate_options(options)
    payload = {"topic": master_brief, "master_brief": master_brief, "goal": goal, "platform": platform,
               "created_at": datetime.now(timezone.utc).isoformat(), "brief_chars": len(master_brief)}
    task = holdings.queue_task(scope_id, "media", "short_story", payload, requires_approval=False)
    if options is not None:
        record={'payload':payload,'project':project,'checkpoint':{},'status':'QUEUED'}
        _save(scope_id,task['id'],record)
        _mirror(scope_id,task,record)
    return task


def produce_local(scope_id, task_id):
    """Compatibility entrypoint: authorizes asynchronous DIRECT work, never local video."""
    task = _task(scope_id, task_id)
    _client()  # Validate configuration before starting the existing worker.
    if holdings.read(scope_id).get("global_stop"):
        raise ValueError("Holdings está detenido; reanúdalo antes de producir.")
    with _job_lock(scope_id, task_id) as locked:
        if not locked:
            return {"ok": True, "task_id": task_id, "status": "PRODUCING"}
        record = _read(scope_id, task_id) or {"payload": task["payload"], "checkpoint": {}}
        project=record.get('project')
        if project and not record.get('checkpoint'):
            record['checkpoint']={'project_config':{'spine_template':'narrated','narration_style':'third_person',
                'aspect_ratio':project['format'],'add_subtitles':project['subtitles'],
                'visual_style':project['visual_style'],'video_resolution':{'9:16':'720x1280','16:9':'1280x720','1:1':'720x720'}[project['format']]},'music':project['music']}
        if record.get("status") not in {"PRODUCED", "PUBLISHED", "PUBLISHING"}:
            record.update(status="PRODUCING", error=None)
            _save(scope_id, task_id, record)
            _mirror(scope_id, task, record)
        holdings.set_company_state(scope_id, "media", "start")
        return {"ok": True, "task_id": task_id, "status": record["status"], **_result(task, record)}


def _narrator():
    from . import voice_pro
    if not voice_pro._eleven_configured() and not voice_pro._f5_url():
        return None
    from .media_adapters import VoiceAdapter
    return VoiceAdapter().synthesize("Esta es la voz del narrador. Una historia comienza con una idea y cobra vida en cada escena.")


def process_one(scope_id):
    state = holdings.read(scope_id)
    if state.get("global_stop") or state["companies"]["media"].get("state") != "RUNNING":
        return "Media: pausado."
    # Canonical checkpoint wins over a stale Holdings mirror after an interrupted write.
    for task in state["companies"]["media"].get("queue", []):
        record = _read(scope_id, task["id"])
        if record.get("status") == "PUBLISHING":
            with _job_lock(scope_id, task["id"]) as locked:
                if locked:
                    record = _read(scope_id, task["id"])
                    _resume_publication(scope_id, task, record)
                    return "Media: comprobando publicación confirmada."
            continue
        if record.get("status") != "PRODUCING":
            continue
        with _job_lock(scope_id, task["id"]) as locked:
            if not locked:
                continue
            record = _read(scope_id, task["id"])
            if record.get("status") != "PRODUCING":
                continue
            def persist(cp):
                record["checkpoint"] = cp
                _save(scope_id, task["id"], record)
            try:
                from .media_projects import STAGE_AGENT
                agent=STAGE_AGENT.get((record.get('checkpoint') or {}).get('stage','project'),'StoryAgent')
                if state.get('orchestration',{}).get('agents',{}).get(agent,{}).get('state') in {'PAUSED','OFF'}:
                    return 'Media: capacidad '+agent+' pausada.'
                client = _client()
                brief=record['payload']['master_brief']
                if record.get('project'):
                    brief += '\n\nPREFERENCIAS DE PRODUCCIÓN ZAR (duración objetivo, no medida):\n'+json.dumps(record['project'],ensure_ascii=False,sort_keys=True)
                cp = client.advance(record.get("checkpoint") or {}, brief, persist,
                                    narrator=_narrator)
                persist(cp)
                if cp.get("status") == "done":
                    artifact = _path(scope_id, task["id"]).with_suffix(".mp4")
                    if not artifact.exists():
                        client.download_final(cp, artifact)
                    record.update(status="PRODUCED", artifact=artifact.name, error=None,rendered_at=holdings._now(),file_size=artifact.stat().st_size)
                elif cp.get("status") in {"error", "blocked"}:
                    record.update(status="ERROR", error=cp.get("error") or "DramaClaw requiere revisión en su editor.")
                _save(scope_id, task["id"], record)
            except DramaClawError as exc:
                record.update(status='ERROR',error=str(exc))
                _save(scope_id,task['id'],record)
            except Exception:
                # Do not disclose URLs, tokens, provider bodies or narration errors.
                record.update(status="ERROR", error="DramaClaw no disponible o generación interrumpida. Reanuda el trabajo existente; no se usará fallback local.")
                _save(scope_id, task["id"], record)
            _mirror(scope_id, task, record)
            return "Media: " + (record.get("error") or _result(task, record)["stage_label"])
    return "Media: esperando una producción autorizada."


def edit_story(scope_id, task_id, notes):
    task = _task(scope_id, task_id)
    if not str(notes or "").strip():
        raise ValueError("Faltan instrucciones de edición.")
    with _job_lock(scope_id, task_id) as locked:
        if not locked:
            raise ValueError("El trabajo está avanzando; espera a que termine la etapa.")
        record = _read(scope_id, task_id)
        cp = record.get("checkpoint") or {}
        if record.get("status") in {"PRODUCING", "PUBLISHING"} or cp.get("pending") or cp.get("pending_intent"):
            raise ValueError("Resuelve primero la tarea activa en DramaClaw para evitar generaciones duplicadas.")
        payload = dict(record.get("payload") or task["payload"])
        payload.setdefault("original_master_brief", payload["master_brief"])
        payload["master_brief"] += "\n\nEDICIONES SOLICITADAS POR EL USUARIO:\n" + str(notes)
        payload.update(topic=payload["master_brief"], brief_chars=len(payload["master_brief"]), edit_notes=str(notes))
        history = (record.get("history") or []) + ([cp] if cp else [])
        record = {**record, "payload": payload, "checkpoint": {}, "status": "QUEUED", "history": history, "review_approved": False}
        record.pop('artifact', None)
        # New revision must not reuse the preceding MP4.
        archive_render(scope_id,task_id,record)
        _save(scope_id, task_id, record)
        _mirror(scope_id, task, record)
    return {"ok": True, "task_id": task_id, "status": "QUEUED", "message": "Edición preparada para regenerar en DramaClaw."}


def archive_render(scope_id,task_id,record):
    import uuid
    path=_path(scope_id,task_id).with_suffix('.mp4')
    if path.is_file():
        saved=path.with_name(path.stem+'-revision-'+uuid.uuid4().hex[:12]+'.mp4')
        path.replace(saved)
        record.setdefault('renders',[]).append({'filename':saved.name,'timestamp':holdings._now(),'source':'previous_revision'})
    record.pop('subtitle_render',None)
    record.pop('publish',None)


def video_path(scope_id, task_id, previous=False):
    _task(scope_id, task_id)
    record = _read(scope_id, task_id)
    if previous:
        old=next((r for r in reversed(record.get("renders",[])) if r.get("source")=="previous_revision"),None)
        if not old: raise ValueError("Sin render anterior.")
        filename=old.get("filename","")
        if not re.fullmatch(re.escape(task_id)+r"-revision-[a-f0-9]{12}\.mp4",filename): raise ValueError("Revisión inválida.")
        path=_root(scope_id)/filename
        if not path.is_file(): raise ValueError("Revisión no disponible.")
        return path
    if not record.get("artifact"):
        raise ValueError("El MP4 final aún no está disponible.")
    path = _path(scope_id, task_id).with_suffix(".mp4")
    if not path.is_file():
        raise ValueError("MP4 no disponible en almacenamiento persistente.")
    return path


def publish(scope_id, task_id, video_url, platform, caption="", confirmed=False, metadata=None):
    _task(scope_id, task_id)
    if confirmed is not True:
        return {"ok": False, "requires_review": True, "message": "Confirma la publicación de este MP4."}
    if platform not in {"youtube", "tiktok", "instagram", "reels"}:
        raise ValueError("Plataforma no soportada.")
    metadata=metadata or {}
    privacy=metadata.get('privacy','private')
    title=metadata.get('title') or 'Historia ZAR'
    if platform=='youtube':
        if privacy not in {'private','unlisted','public'} or not isinstance(title,str) or not title.strip() or len(title)>100 or len(caption)>5000:raise ValueError('Revisa título, descripción y privacidad YouTube.')
        if metadata.get('publish_at'):
            if privacy!='private':raise ValueError('Una subida programada de YouTube debe ser privada hasta su publicación.')
            stamp=datetime.fromisoformat(str(metadata['publish_at']).replace('Z','+00:00'))
            if stamp.tzinfo is None or stamp<=datetime.now(timezone.utc):raise ValueError('Programación requiere fecha futura con zona horaria.')
        if not isinstance(metadata.get('tags',[]),list):raise ValueError('Tags requieren lista.')
    with _job_lock(scope_id, task_id) as locked:
        if not locked:
            return {"ok": False, "error": "Media está procesando esta tarea."}
        record = _read(scope_id, task_id)
        if holdings.read(scope_id).get('global_stop'):
            raise ValueError('STOP GLOBAL activo; publicación bloqueada.')
        if record.get('project') and not record.get('review_approved'):
            raise ValueError('Aprueba revisión del vídeo antes de publicar.')
        if record.get("publish"):
            previous=record['publish']
            if previous.get('pending_publish') or previous.get('platform')==platform:
                return dict(previous)
            if not previous.get('ok'): raise ValueError('Resuelve primero la publicación anterior.')
        prior=next((p for p in record.get('publications',[]) if p.get('platform')==platform and p.get('revision')==len(record.get('history',[]))),None)
        if prior: return dict(prior)
        video_path(scope_id, task_id)
        if platform=='youtube':
            from .media_adapters import PublishingAdapter
            readiness=PublishingAdapter().prepare_youtube(scope_id,title,caption,privacy=privacy)
            if not readiness['upload_capability']:return readiness
        # This URL is minted by our authenticated route, never supplied by the browser.
        record["publish"] = {"ok": False, "pending_publish": True,
                             "platform":platform,"timestamp":holdings._now(),"status":"PENDING","url":None,"metrics":None,
                             "message": "Solicitud registrada; comprueba la red social antes de reintentar."}
        _save(scope_id, task_id, record)  # Ambiguous failures must not duplicate posts.
        try:
            if platform == 'youtube':
                from .media_adapters import PublishingAdapter
                safe = PublishingAdapter().youtube(video_path(scope_id,task_id),
                    title, caption,scope_id=scope_id,privacy=privacy,tags=metadata.get('tags'),publish_at=metadata.get('publish_at'))
                record.update(publish=safe,status='PUBLISHED')
                record.setdefault('publications',[]).append(dict(safe,revision=len(record.get('history',[]))))
                _save(scope_id,task_id,record);_mirror(scope_id,_task(scope_id,task_id),record)
                return safe
            publish_fn = tiktok_direct_post if platform == "tiktok" else instagram_reel
            result = publish_fn(video_url, caption, confirmed=True, **({'privacy':metadata.get('privacy','SELF_ONLY')} if platform=='tiktok' else {}))
            # Only known identifiers/status enter persistence; never raw provider errors.
            safe = {k: result[k] for k in ("ok", "pending_publish", "publish_id", "container_id", "id") if k in result}
            if platform == "tiktok" and (result.get("data") or {}).get("publish_id"):
                safe.update(publish_id=result["data"]["publish_id"], pending_publish=True)
            safe["platform"] = platform
            safe.update(timestamp=holdings._now(),url=None,metrics=None,status='PENDING' if safe.get('pending_publish') else 'PUBLISHED' if safe.get('ok') else 'ERROR')
            safe["message"] = "Publicación enviada." if safe.get("ok") else "Publicación no completada; comprueba el conector social."
        except Exception:
            safe = record["publish"]
        record.update(publish=safe, status="PUBLISHING" if safe.get("pending_publish") else "PUBLISHED" if safe.get("ok") else "PRODUCED")
        record.setdefault('publications',[]).append(dict(safe,revision=len(record.get('history',[]))))
        _save(scope_id, task_id, record)
        _mirror(scope_id, _task(scope_id, task_id), record)
        return safe


def _resume_publication(scope_id, task, record):
    """Poll only the already confirmed post/container, never recreate either."""
    publication = record.get('publish') or {}
    if record.get('status') != 'PUBLISHING' or not publication.get('pending_publish'):
        return
    try:
        if publication.get('platform') == 'tiktok' and publication.get('publish_id'):
            token = os.environ.get('TIKTOK_ACCESS_TOKEN', '').strip()
            if not token: return
            response = requests.post('https://open.tiktokapis.com/v2/post/publish/status/fetch/',
                headers={'Authorization': 'Bearer ' + token}, json={'publish_id': publication['publish_id']},
                timeout=15, allow_redirects=False)
            if not response.ok: return
            state = (response.json().get('data') or {}).get('status')
            if state == 'PUBLISH_COMPLETE':
                publication.update(ok=True, pending_publish=False, message='Publicado en TikTok.')
                record['status'] = 'PUBLISHED'
            elif state == 'FAILED':
                publication.update(ok=False, pending_publish=False, message='TikTok no completó la publicación.')
                record['status'] = 'PRODUCED'
        elif publication.get('platform') in {'instagram', 'reels'} and publication.get('container_id'):
            token = os.environ.get('INSTAGRAM_ACCESS_TOKEN', '').strip()
            user = os.environ.get('INSTAGRAM_IG_USER_ID', '').strip()
            if not token or not user: return
            version = os.environ.get('META_GRAPH_VERSION', 'v24.0')
            base = 'https://graph.facebook.com/' + version
            response = requests.get(base + '/' + publication['container_id'],
                params={'fields': 'status_code', 'access_token': token}, timeout=15, allow_redirects=False)
            if not response.ok: return
            state = response.json().get('status_code')
            if state == 'FINISHED' and not publication.get('commit_intent'):
                publication['commit_intent'] = True
                _save(scope_id, task['id'], record)
                response = requests.post(base + '/' + user + '/media_publish',
                    params={'creation_id': publication['container_id'], 'access_token': token},
                    timeout=15, allow_redirects=False)
                if response.ok and response.json().get('id'):
                    publication.update(ok=True, pending_publish=False, id=response.json()['id'], message='Publicado en Reels.')
                    record['status'] = 'PUBLISHED'
            elif state == 'PUBLISHED':
                publication.update(ok=True, pending_publish=False, message='Publicado en Reels.')
                record['status'] = 'PUBLISHED'
            elif state in {'ERROR', 'EXPIRED'}:
                publication.update(ok=False, pending_publish=False, message='Reels no completó la publicación.')
                record['status'] = 'PRODUCED'
        publication['status']='PENDING' if publication.get('pending_publish') else 'PUBLISHED' if publication.get('ok') else 'ERROR'
        for saved in record.get('publications',[]):
            if saved.get('platform')==publication.get('platform') and saved.get('revision')==len(record.get('history',[])):
                saved.update(publication)
        _save(scope_id, task['id'], record)
        _mirror(scope_id, task, record)
    except Exception:
        # Preserve IDs and submission intent; transient/ambiguous failures never repost.
        pass
