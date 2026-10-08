"""Cost records preserve unknown billing; configuration never proves charges."""
class RelayClawCostTracker:
    @staticmethod
    def record(job_id, record):
        from datetime import datetime,timezone
        cp=record.get('checkpoint') or {};project=record.get('project') or {}
        previous=record.get('costs') or {}
        return {'job_id':job_id,'project_id':cp.get('project_id'),'timestamp':previous.get('timestamp') or record.get('created_at') or datetime.now(timezone.utc).isoformat(),
                'task_id':(cp.get('active_task') or {}).get('task_id'),'started_at':record.get('created_at'),'finished_at':record.get('finished_at'),'operations':cp.get('tasks',[]),'tokens':previous.get('tokens'),'images_generated':previous.get('images_generated'),'video_seconds':previous.get('video_seconds'),'audio_seconds':previous.get('audio_seconds'),'provider':'RelayClaw','models_used':previous.get('models_used',[]),
                **{name:previous.get(name) for name in ('text_cost','image_cost','video_cost','audio_cost','total_cost','currency')},
                'duration':project.get('duration'),'number_of_scenes':len(record.get('scenes',[])) or None,
                'regenerations':max(0,len(record.get('renders',[]))-1),
                'source':previous.get('source','NO_VERIFIED_USAGE_LOGS'),
                'estimated_cost':None,'estimate_message':'El proveedor no ofrece datos suficientes para calcular una estimación fiable.'}
