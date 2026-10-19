"""Bounded CPU assembly for the existing local worker. No publication or remote code."""
import json
import math
import re
import subprocess
from pathlib import Path
import requests
from PIL import Image,ImageDraw,ImageFont


def run(command,cwd=None,timeout=180):
    result=subprocess.run(command,cwd=cwd,capture_output=True,timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:raise ValueError('LOCAL_MEDIA_COMMAND_FAILED')
    return result


def inspect(path,binary):
    result=subprocess.run([binary,'-hide_banner','-protocol_whitelist','file,pipe','-i',str(path)],capture_output=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    info=result.stderr.decode(errors='replace');match=re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)',info)
    if not match:raise ValueError('MEDIA_DURATION_UNVERIFIED')
    h,m,s=map(float,match.groups());size=re.search(r'Video:.*?\b(\d{3,5})x(\d{3,5})\b',info)
    return {'duration':h*3600+m*60+s,'audio':'Audio:' in info,'width':int(size[1]) if size else None,'height':int(size[2]) if size else None,'h264':'Video: h264' in info}


def system_voice(text,target,language):
    """Windows' installed speech engine; text is read as data, never shell code."""
    source=target.with_suffix('.txt');source.write_text(text,encoding='utf-8')
    script=Path(__file__).with_name('text_video_voice.ps1')
    result=run(['powershell.exe','-NoProfile','-NonInteractive','-File',str(script),'-TextFile',str(source),'-OutputFile',str(target),'-Language',language],timeout=60)
    return json.loads(result.stdout.decode('utf-8-sig'))


def card(target,title,caption):
    image=Image.new('RGB',(1080,1920),'#17130f');draw=ImageDraw.Draw(image)
    try:font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',58);small=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',34)
    except OSError:font=ImageFont.load_default(size=58);small=ImageFont.load_default(size=34)
    def lines(text,font,limit=880):
        rows=[];line=''
        for word in text.split():
            if draw.textlength((line+' '+word).strip(),font=font)>limit and line:rows.append(line);line=word
            else:line=(line+' '+word).strip()
        return rows+[line]
    draw.rectangle((70,245,1010,252),fill='#dab179');draw.text((90,300),'ZAR · VÍDEO',fill='#dab179',font=small)
    y=470
    for line in lines(title,font)[:5]:draw.text((90,y),line,font=font,fill='#f2e7d6');y+=80
    y=max(1030,y+100)
    for line in lines(caption,small)[:7]:draw.text((90,y),line,font=small,fill='#c7b69d');y+=52
    image.save(target)


def comfy_visual(scene,folder,index,workflow_path):
    """Only a locally installed, explicitly configured workflow can run on loopback."""
    if not workflow_path.is_file():return None,'LOCAL_COMFY_WORKFLOW_NOT_CONFIGURED'
    with requests.Session() as client:
        client.trust_env=False
        health=client.get('http://127.0.0.1:8188/system_stats',timeout=3)
        if health.status_code!=200:return None,'LOCAL_COMFY_UNAVAILABLE'
        workflow=json.loads(workflow_path.read_text(encoding='utf-8'))
        # A trusted local workflow supplies nodes/models. Cloud prompts replace data only.
        changed=False
        for node in workflow.values():
            for key,value in node.get('inputs',{}).items():
                if value=='ZAR_VISUAL_PROMPT':node['inputs'][key]=scene['visual_prompt'];changed=True
        if not changed:return None,'LOCAL_COMFY_PROMPT_SLOT_REQUIRED'
        response=client.post('http://127.0.0.1:8188/prompt',json={'prompt':workflow},timeout=10);response.raise_for_status()
        identifier=response.json().get('prompt_id')
        if not re.fullmatch(r'[\w-]{1,100}',str(identifier or '')):raise ValueError('LOCAL_COMFY_INVALID_JOB')
        import time
        for _ in range(90):
            time.sleep(2)
            history=client.get('http://127.0.0.1:8188/history/'+identifier,timeout=5).json().get(identifier,{})
            if history.get('status',{}).get('status_str')=='error':return None,'LOCAL_COMFY_GENERATION_FAILED'
            for output in history.get('outputs',{}).values():
                for item in output.get('gifs',[])+output.get('images',[]):
                    name=item.get('filename','');sub=item.get('subfolder','')
                    if item.get('type')!='output' or '/' in name or '\\' in name or '..' in sub or not name.lower().endswith(('.png','.jpg','.webp','.mp4')):continue
                    result=client.get('http://127.0.0.1:8188/view',params={'filename':name,'subfolder':sub,'type':'output'},timeout=30)
                    if result.status_code!=200 or len(result.content)>30*1024*1024:continue
                    path=folder/('generated-'+str(index)+Path(name).suffix.lower());path.write_bytes(result.content)
                    return path,'COMFYUI_LOCAL_WORKFLOW'
        return None,'LOCAL_COMFY_TIMEOUT'


def stamp(seconds):
    ms=round(seconds*1000);return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'


def captions(text,start,duration):
    words=text.split();chunks=[];line=[]
    for word in words:
        if len(' '.join(line+[word]))>60 and line:chunks.append(' '.join(line));line=[]
        line.append(word)
    if line:chunks.append(' '.join(line))
    total=max(1,len(words));position=0;rows=[]
    for chunk in chunks:
        end=position+len(chunk.split());rows.append((start+duration*position/total,start+duration*end/total,chunk));position=end
    return rows


def karaoke(path,rows):
    def ass_time(value):
        cs=round(value*100);return f'{cs//360000:01}:{cs//6000%60:02}:{cs//100%60:02}.{cs%100:02}'
    text='[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\nStyle: Default,Arial,64,&H0000D7FF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,3,0,2,70,70,180,1\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n'
    for start,end,caption in rows:
        words=re.sub(r'[\\{}\r\n]','',caption).split();total=max(1,len(words));used=0;segments=[]
        for i,word in enumerate(words):
            now=round((end-start)*100*(i+1)/total);segments.append('{\\kf'+str(now-used)+'}'+word);used=now
        text+=f'Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,'+ ' '.join(segments)+'\n'
    path.write_text(text,encoding='utf-8')


def assemble(job,folder,binary,workflow_path=None,progress=lambda:None):
    """Every scene has real speech, bounded timing, a real visual or an owned card."""
    folder=Path(folder);segments=[];all_captions=[];sources=[];voices=[];elapsed=0
    width,height=job.get('dimensions',[1080,1920]);style=job.get('caption_style','CLEAN')
    for index,scene in enumerate(job['scenes']):
        progress();duration=float(scene['duration']);audio=folder/('voice-'+str(index)+'.wav')
        if not audio.is_file():
            voice=system_voice(scene['voiceover'],audio,job.get('language','es-ES'));voices.append(voice)
        else:voices.append({'provider':'WINDOWS_INSTALLED_TTS_CACHED' if job.get('voice_provider')=='WINDOWS_INSTALLED_TTS_PENDING' else job.get('voice_provider','ZAR_EXISTING_TTS')})
        audio_info=inspect(audio,binary)
        if not audio_info['audio']:raise ValueError('NARRATION_MISSING')
        ratio=audio_info['duration']/duration
        if ratio>1.8:raise ValueError('NARRATION_TOO_LONG_FOR_SCENE')
        visual=None;provider='ARTICLE_ASSET_MOTION'
        cached=next((p for p in folder.glob('generated-'+str(index)+'.*') if p.suffix in {'.png','.jpg','.webp','.mp4'}),None)
        if scene.get('visual_source')=='DRAMACLAW_GENERATED_MASTER' and re.fullmatch(r'asset-\d+\.png',scene.get('asset_file','')):
            visual=folder/scene['asset_file'];provider='DRAMACLAW_MASTER_FRAME_MOTION'
        elif cached:visual=cached;provider='COMFYUI_LOCAL_WORKFLOW_CACHED'
        elif workflow_path:
            try:visual,provider=comfy_visual(scene,folder,index,Path(workflow_path))
            except (OSError,ValueError,requests.RequestException):provider='LOCAL_COMFY_UNAVAILABLE'
        if not visual:
            asset=scene.get('asset_file');visual=folder/asset if asset and re.fullmatch(r'asset-\d+\.png',asset) else None
            if not visual or not visual.is_file():visual=folder/('card-'+str(index)+'.png');card(visual,scene['title'],scene['voiceover']);provider+=' → OWNED_TEXT_MOTION'
            else:provider+=' → ARTICLE_ASSET_MOTION'
        sources.append({'scene':index,'provider':provider,'source':scene.get('visual_source'),'rights':scene.get('rights','OWNED')})
        cue_rows=captions(scene['voiceover'],0,duration);srt=folder/('scene-'+str(index)+'.srt')
        srt.write_text('\n'.join(f'{i+1}\n{stamp(a)} --> {stamp(b)}\n{t}\n' for i,(a,b,t) in enumerate(cue_rows)),encoding='utf-8')
        all_captions.extend((a+elapsed,b+elapsed,t) for a,b,t in cue_rows);elapsed+=duration
        output=folder/('scene-'+str(index)+'.mp4');segments.append(output.name)
        # Only fixed local names enter the filter graph; prompts never enter FFmpeg syntax.
        filters=f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x17130f,setsar=1'
        if visual.suffix!='.mp4':filters+=f",zoompan=z='min(1+on*0.00012,1.06)':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={width}x{height}:fps=30"
        filters+=f',fade=t=in:st=0:d=0.15,fade=t=out:st={max(0,duration-.15):.3f}:d=0.15'
        styles={'CLEAN':'FontSize=12,Outline=2','MODERN':'FontSize=13,BorderStyle=3,BackColour=&H80000000','HIGHLIGHT':'FontSize=13,Bold=1,PrimaryColour=&H0000D7FF,Outline=3'}
        if style=='KARAOKE':
            ass=folder/('scene-'+str(index)+'.ass');karaoke(ass,cue_rows);filters+=',ass='+ass.name
        else:filters+=f",subtitles={srt.name}:force_style='{styles[style]},Alignment=2,MarginV=30'"
        command=[binary,'-y','-protocol_whitelist','file,pipe']+(['-stream_loop','-1'] if visual.suffix=='.mp4' else ['-loop','1'])+['-i',visual.name,'-i',audio.name,'-vf',filters,'-af',f'atempo={max(.8,min(1.8,ratio)):.5f},apad,atrim=0:{duration:.5f}','-t',str(duration),'-r','30','-c:v','libx264','-preset','ultrafast','-threads','2','-crf','24','-pix_fmt','yuv420p','-c:a','aac','-ar','48000','-ac','2',output.name]
        run(command,cwd=folder,timeout=240)
    concat=folder/'segments.txt';concat.write_text('\n'.join("file '"+name+"'" for name in segments),encoding='utf-8')
    output=folder/'result.mp4';run([binary,'-y','-f','concat','-safe','1','-i',concat.name,'-c','copy','-movflags','+faststart',output.name],cwd=folder)
    metadata=inspect(output,binary)
    if not metadata['h264'] or not metadata['audio'] or [metadata['width'],metadata['height']]!=[width,height] or abs(metadata['duration']-elapsed)>.35:raise ValueError('FINAL_VIDEO_VALIDATION_FAILED')
    srt=folder/'subtitles.srt';srt.write_text('\n'.join(f'{i+1}\n{stamp(a)} --> {stamp(b)}\n{t}\n' for i,(a,b,t) in enumerate(all_captions)),encoding='utf-8')
    thumb=folder/'thumbnail.png';run([binary,'-y','-ss','0.6','-i',output.name,'-frames:v','1',thumb.name],cwd=folder,timeout=30)
    return {'metadata':metadata,'visuals':sources,'voices':voices,'caption_timing':'NARRATION_SCENE_TIMING_ESTIMATED_WITHIN_SCENE','music':{'status':'NONE','rights':'NO_TRACK_USED'},'assembly':'ZAR_FFMPEG_SCENE_VOICE_CAPTIONS_MOTION','karaoke_word_alignment':False}
