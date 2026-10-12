"""Non-executing recovery assessment: preserve checkpoints and provider evidence."""


def assess(record):
    cp = record.get('checkpoint') or {}
    state = record.get('status')
    scenes = record.get('scenes') or []
    assets = {key: sum(bool(s.get(key)) for s in scenes)
              for key in ('frame_url', 'audio_url', 'video_url')}
    assets.update(script=bool(record.get('script')), characters=len(record.get('characters') or []),
                  mp4=bool(record.get('artifact')))
    unknown = cp.get('error_code') in {'submission_unknown', 'task_missing', 'task_status'} or bool(cp.get('pending'))
    if record.get('archived_at'):
        category, action = 'TEST' if record.get('is_test') else 'STALE', 'ARCHIVED · fuentes y checkpoint conservados; restaurar no reanuda.'
    elif state in {'PRODUCING', 'PUBLISHING'}:
        category, action = 'ACTIVE', 'Consultar progreso; no duplicar solicitudes.'
    elif unknown:
        category, action = 'FAILED_EXTERNAL', 'Envío incierto: revisar la tarea en DramaClaw antes de repetir; no se autoriza nuevo gasto.'
    elif state == 'PAUSED' and cp.get('project_id'):
        category, action = 'RECOVERABLE', 'Checkpoint conservado. Inspeccionar recursos; continuar puede consumir cuota y requiere revisión.'
    elif state == 'ERROR':
        category, action = 'FAILED_EXTERNAL' if cp.get('project_id') else 'FAILED_INTERNAL', 'Revisar la etapa fallida y su evidencia; no regenerar desde cero.'
    else:
        category, action = 'ACTIVE', 'Conservar el resultado y revisar antes de publicar.'
    return {'classification': category, 'stage': cp.get('stage', 'project'), 'assets': assets,
            'archived': bool(record.get('archived_at')), 'is_test': bool(record.get('is_test')),
            'action': action, 'automatic_retry': False}
