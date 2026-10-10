"""Explicit single-frame smoke render; preserves all DramaClaw checkpoints."""
import json
import shutil
import subprocess
from urllib.parse import urlsplit, unquote
from . import holdings, media_company as media


def queue(scope, task_id, confirmed=False):
    if confirmed is not True:
        raise ValueError('Confirma el render del frame existente; no es vídeo generativo.')
    task=media._task(scope,task_id)
    if holdings.read(scope).get('global_stop'):
        raise ValueError('STOP GLOBAL activo.')
    with media._job_lock(scope,task_id) as locked:
        if not locked: raise ValueError('Etapa activa.')
        record=media._read(scope,task_id);cp=record.get('checkpoint',{})
        if record.get('artifact'): return {'status':'PRODUCED','task_id':task_id}
        if cp.get('stage')!='audio' or cp.get('pending'):
            raise ValueError('Fallback disponible únicamente tras un fallo confirmado de audio.')
        remote=media._client()._tasks(cp)
        active=cp.get('active_task',{})
        failed=next((t for t in remote if t.get('task_id')==active.get('task_id')),None)
        if not failed or failed.get('status')!='failed' or 'ORG_EGRESS_DENIED' not in str(failed.get('error','')):
            raise ValueError('IndexTTS2 no tiene un bloqueo ORG_EGRESS_DENIED confirmado.')
        if record.get('fallback',{}).get('status') in {'QUEUED','RUNNING','DONE'}:
            return {'status':record['fallback']['status'],'task_id':task_id}
        record.setdefault('fallback',{}).update(status='QUEUED',reason='ORG_EGRESS_DENIED',mode='existing_frame',confirmed_at=holdings._now())
        record.update(status='PRODUCING',error=None)
        media._save(scope,task_id,record);media._mirror(scope,task,record)
        holdings.set_company_state(scope,'media','start')
    return {'status':'PRODUCING','task_id':task_id}


def frame_path(cp, value, audio=False):
    """Use the configured authenticated project API, never a supplied origin."""
    path=unquote(urlsplit(str(value)).path)
    prefix='/static/projects/'+cp['project_id']+'/'
    if not path.startswith(prefix): raise ValueError('Frame fuera del proyecto.')
    relative=path[len(prefix):]
    extensions=('.wav','.mp3','.m4a','.ogg') if audio else ('.png','.jpg','.jpeg','.webp')
    if '..' in relative.split('/') or '\\' in relative or not relative.lower().endswith(extensions):
        raise ValueError('Ruta del frame inválida.')
    return relative


def probe(path):
    result=subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],capture_output=True,timeout=20)
    if result.returncode: raise ValueError('MP4 no verificable.')
    data=json.loads(result.stdout);video=next((x for x in data['streams'] if x['codec_type']=='video'),{})
    duration=float(data['format'].get('duration',0))
    if duration<=0 or video.get('codec_name')!='h264' or path.stat().st_size<=0:
        raise ValueError('MP4 sin duración o codec reproducible.')
    return {'duration':duration,'width':video['width'],'height':video['height'],'codec':'h264','mime':'video/mp4','size':path.stat().st_size}


def render(scope, task, record):
    task_id=task['id'];cp=record['checkpoint'];fallback=record['fallback']
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise ValueError('FFmpeg/FFprobe requeridos para el fallback.')
    client=media._client();beats=client._beats(cp)
    if len(beats)!=1 or not beats[0].get('frame_url'):
        raise ValueError('Smoke limitado a un frame existente; no se regeneran visuales.')
    text='Render de prueba · muestra de voz existente'
    if len(text)>500: raise ValueError('Narración demasiado larga para el smoke.')
    base=media._path(scope,task_id);image=base.with_suffix('.fallback.jpg')
    if not image.is_file():
        route='/api/v1'+client._project(cp)+'/media/'+frame_path(cp,beats[0]['frame_url'])
        response=client.session.get(client.base_url+route,headers=client.headers,timeout=(5,30),allow_redirects=False,stream=True)
        with response:
            if response.status_code!=200 or not response.headers.get('Content-Type','').startswith('image/'):
                raise ValueError('Frame existente no accesible mediante API.')
            temp=image.with_suffix('.part');size=0
            try:
                with temp.open('wb') as handle:
                    for chunk in response.iter_content(65536):
                        size+=len(chunk)
                        if size>20*1024*1024: raise ValueError('Frame demasiado grande.')
                        handle.write(chunk)
                if not size: raise ValueError('Frame vacío.')
                temp.replace(image)
            finally: temp.unlink(missing_ok=True)
    audio=base.with_suffix('.fallback.wav')
    if not audio.is_file():
        voice=client._get(client._project(cp)+'/narrator-voice') or {}
        reference=voice.get('reference_url')
        if not reference: raise ValueError('Carga una muestra TTS real antes del smoke.')
        route='/api/v1'+client._project(cp)+'/media/'+frame_path(cp,reference,audio=True)
        response=client.session.get(client.base_url+route,headers=client.headers,timeout=(5,30),allow_redirects=False)
        if response.status_code!=200 or len(response.content)>10*1024*1024 or not response.content:
            raise ValueError('Muestra de narración no accesible.')
        if not response.headers.get('Content-Type','').startswith(('audio/','application/octet-stream')):
            raise ValueError('MIME de audio no válido.')
        audio.write_bytes(response.content)
        fallback.update(voice_provider='existing_narrator_sample',voice_mime=response.headers.get('Content-Type'),status='RUNNING')
        media._save(scope,task_id,record)
    audio_probe=subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(audio)],capture_output=True,timeout=20)
    if audio_probe.returncode: raise ValueError('Audio inválido; muestra conservada.')
    audio_data=json.loads(audio_probe.stdout)
    if float(audio_data['format'].get('duration',0))<=0 or not any(x.get('codec_type')=='audio' for x in audio_data.get('streams',[])):
        raise ValueError('Muestra sin duración de audio válida.')
    srt=base.with_suffix('.srt');srt.write_text('1\n00:00:00,000 --> 00:00:05,000\n'+text.replace('\n',' ')+'\n',encoding='utf-8')
    dimensions={'9:16':(720,1280),'16:9':(1280,720),'1:1':(720,720)}
    width,height=dimensions.get((record.get('project') or {}).get('format'),(720,1280))
    output=base.with_suffix('.mp4');temp=base.with_suffix('.render.mp4')
    # Run from the scoped directory so subtitle paths need no shell escaping.
    vf=f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,subtitles={srt.name}'
    command=['ffmpeg','-y','-loop','1','-i',image.name,'-i',audio.name,'-vf',vf,'-af','apad','-t','5','-r','25','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-movflags','+faststart',temp.name]
    result=subprocess.run(command,cwd=base.parent,capture_output=True,timeout=120)
    if result.returncode: raise ValueError('Render local no confirmado; audio y frame conservados.')
    metadata=probe(temp);temp.replace(output)
    fallback.update(status='DONE',metadata=metadata,rendered_at=holdings._now())
    record.update(status='PRODUCED',artifact=output.name,file_size=output.stat().st_size,rendered_at=fallback['rendered_at'],error=None,review_approved=False,
                  subtitles={'file':srt.name,'text':srt.read_text(encoding='utf-8'),'enabled':True,'source':'smoke_caption_not_transcript'})
    media._save(scope,task_id,record)
