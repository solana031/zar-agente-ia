"""Explicit video assembly jobs for the already paired ZAR worker."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import requests
from .scoped_http import BearerAuth
from .text_video_render import assemble


def poll_once(config,root,binary):
    if config.get('cloud')!='https://web-production-a9565.up.railway.app':raise ValueError('INVALID_WORKER_CONFIG')
    with requests.Session() as client:
        client.trust_env=False;client.auth=BearerAuth(config['token']);base=config['cloud']+'/api/video-projects/local-worker'
        response=client.post(base+'/poll',json={},timeout=(5,15),allow_redirects=False)
        if response.status_code==404:return False  # Compatible with the previous server during rollout.
        response.raise_for_status();job=response.json().get('job')
        if not job:return False
        if job.get('kind')!='RENDER_TEXT_VIDEO' or not re.fullmatch(r'[a-f0-9]{16}',job.get('id','')) or not re.fullmatch(r'[a-f0-9]{24}',job.get('render_key','')):raise ValueError('INVALID_VIDEO_JOB')
        folder=Path(root)/job['id']/job['render_key'];folder.mkdir(parents=True,exist_ok=True)
        endpoint=base+'/'+job['id'];headers={'X-ZAR-Video-Lease':job['lease']}
        def progress():
            r=client.post(endpoint+'/progress',json={},headers=headers,timeout=(5,40),allow_redirects=False);r.raise_for_status()
        try:
            for name in job.get('files',[]):
                if not re.fullmatch(r'(asset-\d+\.png|voice-\d+\.wav)',name):raise ValueError('INVALID_VIDEO_ASSET')
                target=folder/name
                if target.is_file():continue
                r=client.get(endpoint+'/asset/'+name,headers=headers,timeout=(5,25),allow_redirects=False)
                r.raise_for_status()
                if not 0<len(r.content)<=12*1024*1024:raise ValueError('VIDEO_ASSET_SIZE_LIMIT')
                target.write_bytes(r.content)
            saved=folder/'render-report.json'
            if saved.is_file() and (folder/'result.mp4').is_file():manifest=json.loads(saved.read_text(encoding='utf-8'))
            else:
                manifest=assemble(job,folder,binary,workflow_path=Path(root).parent/'comfy-workflow.json',progress=progress)
                saved.write_text(json.dumps(manifest),encoding='utf-8')
            progress()
            with (folder/'result.mp4').open('rb') as video,(folder/'subtitles.srt').open('rb') as subtitles,(folder/'thumbnail.png').open('rb') as thumbnail:
                r=client.post(endpoint+'/result',headers=headers,data={'manifest':json.dumps(manifest)},files={'video':('result.mp4',video,'video/mp4'),'subtitles':('subtitles.srt',subtitles,'text/plain'),'thumbnail':('thumbnail.png',thumbnail,'image/png')},timeout=(10,240),allow_redirects=False)
                r.raise_for_status()
            (Path(root).parent/'last-video.json').write_text(json.dumps({'id':job['id'],'metadata':manifest['metadata'],'assembly':manifest['assembly'],'visual_providers':[v['provider'] for v in manifest['visuals']],'voice_providers':[v['provider'] for v in manifest['voices']]},indent=2),encoding='utf-8')
        except (ValueError,OSError,requests.RequestException,subprocess.SubprocessError) as exc:
            # An uncertain upload is reconciled by server status; never regenerate it.
            if (folder/'render-report.json').is_file():raise
            code=str(exc) if isinstance(exc,ValueError) and re.fullmatch(r'[A-Z0-9_]{1,90}',str(exc)) else 'LOCAL_RENDER_FAILED'
            client.post(endpoint+'/result',headers=headers,data={'manifest':json.dumps({'error':code})},timeout=(5,15),allow_redirects=False).raise_for_status()
        return True
