"""Adapters reuse ZAR's official DramaClaw client and publishing integrations."""
import os
import re
from urllib.parse import quote
import requests
import subprocess
import shutil
import uuid
from . import holdings


class DramaClawAdapter:
    def __init__(self, client):
        self.client = client

    def inspect(self, cp):
        root, ep = self.client._project(cp), self.client._episode(cp)
        chars = self.client._get(root+'/characters') or []
        beats = self.client._beats(cp)
        return {'characters':[{'name':c.get('name'),'description':c.get('description'),
                    'gender':c.get('gender'),'voice':None,'language':None,'provider_reference':None,'voice_preview':None} for c in chars],
            'scenes':[{k:b.get(k) for k in ('beat_number','narration_segment','visual_description','sketch_url','frame_url','audio_url','video_url')} for b in beats],
            'script':self.client._get(ep+'/script'), 'provider':'DramaClaw DIRECT','updated_at':holdings._now()}

    def regenerate_scene(self, cp, scene, persist):
        if cp.get('pending') or cp.get('active_task') or cp.get('active_tasks'):
            raise ValueError('Resuelve la tarea activa antes de regenerar.')
        if not any(b['beat_number']==scene for b in self.client._beats(cp)):
            raise ValueError('Escena no encontrada en DramaClaw.')
        cp.update(stage='frames',status='running')
        cp['forced_video_beats']=[scene]
        cp['force_compose']=True
        # Remove only matching completed evidence; checkpoint history is retained by caller.
        cp['tasks'] = [t for t in cp.get('tasks',[]) if t.get('target') != {'beat_num':scene}]
        return self.client._submit(cp,persist,self.client._episode(cp)+'/beats/regenerate',
            body={'beat_indices':[scene], 'mode_key':'1x1_2-3'},task_type='selected_regen',episode=cp.get('episode',1),target={'beat_num':scene})


class VoiceAdapter:
    def voices(self):
        key=os.environ.get('ELEVENLABS_API_KEY','').strip()
        if not key:
            return {'state':'POR CONFIGURAR','provider':None,'voices':[]}
        r=requests.get('https://api.elevenlabs.io/v2/voices',headers={'xi-api-key':key},params={'page_size':100},timeout=(5,20),allow_redirects=False)
        if not r.ok:
            raise ValueError('ElevenLabs no confirmó acceso a voces (HTTP '+str(r.status_code)+').')
        rows=r.json().get('voices',[])
        return {'state':'LISTO','provider':'ElevenLabs','next_page_token':r.json().get('next_page_token'),'voices':[{'id':x.get('voice_id'),'name':x.get('name'),
                'preview_url':x.get('preview_url'),'labels':x.get('labels',{})} for x in rows]}

    def synthesize(self,text,voice_id=None,language='es'):
        if not str(text).strip() or len(text)>12000:
            raise ValueError('Texto de audio requerido, máximo 12000 caracteres.')
        key=os.environ.get('ELEVENLABS_API_KEY','').strip()
        if key:
            voice_id=voice_id or os.environ.get('ELEVENLABS_VOICE_ID','').strip()
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,150}',str(voice_id or '')):
                raise ValueError('Selecciona una voz de ElevenLabs.')
            r=requests.post('https://api.elevenlabs.io/v1/text-to-speech/'+quote(voice_id,safe=''),
                headers={'xi-api-key':key,'Accept':'audio/mpeg'},json={'text':text,'model_id':os.environ.get('ELEVENLABS_MODEL_ID','eleven_multilingual_v2')},
                timeout=(5,90),allow_redirects=False)
            if not r.ok or not r.headers.get('Content-Type','').startswith('audio/') or not r.content:
                raise ValueError('ElevenLabs no confirmó audio. No se reintentará automáticamente.')
            return r.content, r.headers['Content-Type'].split(';')[0], 'ElevenLabs'
        if os.environ.get('F5_TTS_API_URL','').strip():
            from . import voice_pro
            result=voice_pro._f5_synthesize(text,language=language)
            if result: return result
        raise ValueError('POR CONFIGURAR: ElevenLabs o fallback F5-TTS existente; no se genera audio ficticio.')


class PublishingAdapter:
    def prepare_youtube(self,scope_id,title,description='',privacy='private',thumbnail=None,subtitle_track=None):
        from .identity_center import verify_google,provider_plan
        if privacy not in {'private','unlisted','public'}:raise ValueError('Privacy YouTube no válida.')
        if not str(title).strip() or len(str(title))>100 or len(str(description))>5000:raise ValueError('Título requerido (máximo 100) y descripción máximo 5000 caracteres.')
        state=verify_google(scope_id,services=['YOUTUBE'])
        cap=state.get('capabilities',{}).get('YOUTUBE',{})
        ready=cap.get('status')=='CONNECTED' and cap.get('upload_capability') is True
        if not ready:provider_plan(scope_id,'YOUTUBE')
        return {'ok':True,'dry_run':True,'validation':'LOCAL_AND_READ_ONLY_API','status':'READY_FOR_REVIEW' if ready else 'HUMAN_ACTION_REQUIRED',
            'channel':(cap.get('channels') or [None])[0],'title':title,'description':description,'privacy':privacy,
            'thumbnail':thumbnail,'subtitle_track':subtitle_track,'upload_capability':ready,'publish_capability':cap.get('publish_capability','BLOCKED'),
            'publish_status':'NOT_UPLOADED','message':'Sin subida: YouTube no ofrece dry-run de videos.insert; publicación y assets requieren confirmación posterior.'}

    def youtube(self,path,title,description,scope_id=None,privacy='private',tags=None,publish_at=None):
        if scope_id:
            plan=self.prepare_youtube(scope_id,title,description,privacy=privacy)
            if not plan['upload_capability']:raise ValueError('HUMAN_ACTION_REQUIRED: crear/verificar el canal YouTube de ZAR.')
        from .youtube import upload
        result=upload(path,title,description=description,privacy=privacy,tags=tags,publish_at=publish_at,**({'user_id':scope_id} if scope_id else {}))
        video_id=result.get('id')
        if not video_id:
            raise ValueError('YouTube no confirmó identificador; revisar cuenta antes de reintentar.')
        return {'ok':True,'platform':'youtube','id':video_id,'url':'https://www.youtube.com/watch?v='+quote(video_id,safe=''),
            'status':'SCHEDULED' if publish_at else 'UPLOADED_'+privacy.upper(),'timestamp':holdings._now(),'metrics':None,'pending_publish':False}


class MediaRenderAdapter:
    def check(self):
        from .voice_audio_clean import _ffmpeg_exe
        binary=_ffmpeg_exe()
        try:
            r=subprocess.run([binary,'-filters'],capture_output=True,timeout=10)
            if r.returncode or b'subtitles' not in r.stdout:
                raise ValueError('NO DISPONIBLE: FFmpeg requiere filtro subtitles/libass para incrustar SRT.')
        except (OSError,subprocess.TimeoutExpired):
            raise ValueError('POR CONFIGURAR: FFmpeg/imageio-ffmpeg y libass para render local de subtítulos.') from None
        return binary

    def render(self,path,subtitles,source_path=None):
        binary=self.check()
        source=path.with_name(path.stem+'-clean-'+uuid.uuid4().hex[:12]+'.mp4')
        shutil.copyfile(source_path or path,source)
        if not subtitles.get('enabled'):
            if source_path:shutil.copyfile(source,path)
            return {'clean_source':source.name,'burned_into_video':False}
        if not subtitles.get('text'):
            raise ValueError('Falta SRT sincronizado; no se inventa texto ni tiempos.')
        srt=path.with_suffix('.srt');srt.write_text(subtitles['text'],encoding='utf-8')
        output=path.with_name(path.stem+'-render-'+uuid.uuid4().hex[:12]+'.mp4')
        alignment={'bottom':2,'middle':5,'top':8}[subtitles['position']]
        size=int(subtitles['size'])
        style=f'FontSize={size},Alignment={alignment},Outline=2'
        if subtitles.get('style')=='boxed':style+=',BorderStyle=3,BackColour=&H80000000'
        elif subtitles.get('style')=='high_contrast':style+=',Bold=1,Outline=3,PrimaryColour=&H0000FFFF'
        args=[binary,'-y','-i',source.name,'-vf',f"subtitles={srt.name}:force_style='{style}'",
            '-c:v','libx264','-c:a','copy',output.name]
        try:
            r=subprocess.run(args,cwd=path.parent,capture_output=True,timeout=300)
            if r.returncode or not output.is_file() or output.stat().st_size<12:
                raise ValueError('Render de subtítulos falló; se conserva el vídeo limpio.')
            with output.open('rb') as handle:header=handle.read(12)
            if header[4:8] != b'ftyp':raise ValueError('Render no confirmó MP4.')
            os.replace(output,path)
            return {'clean_source':source.name,'burned_into_video':True}
        except subprocess.TimeoutExpired:
            raise ValueError('Render excedió tiempo permitido; fuente conservada.') from None
        finally:output.unlink(missing_ok=True)
