"""ZAR Media: short-form visual-story pipeline inspired by DramaClaw concepts.

No DramaClaw CE code is embedded.  ZAR can optionally bridge to a separately
self-hosted DramaClaw endpoint while retaining the required attribution/licence.
"""
from __future__ import annotations

import json
import os
import re
import requests
import uuid
import textwrap
from pathlib import Path
from datetime import datetime, timezone

from . import holdings
from .jev_decision import gate
from .social_publish import status as social_status, tiktok_direct_post, instagram_reel


def status():
    url=os.environ.get("DRAMACLAW_API_URL","").strip().rstrip("/")
    return {
        "dramaclaw_bridge_configured": bool(url),
        "dramaclaw_api_url": url,
        "attribution_required": bool(url),
        "social": social_status(),
        "pipeline": ["HOOK","STORY","STORYBOARD","ASSETS","VOICE","EDIT","QA","PUBLISH","ANALYTICS"],
    }


def queue_story(scope_id, topic, goal="retención", platform="tiktok"):
    topic=str(topic or "").strip()
    if not topic: raise ValueError("Falta el tema.")
    payload={"topic":topic,"goal":goal,"platform":platform,"stage":"HOOK","created_at":datetime.now(timezone.utc).isoformat()}
    return holdings.queue_task(scope_id,"media","short_story",payload,requires_approval=False)


def _local_plan(topic, platform):
    clean=re.sub(r"\s+"," ",topic).strip()
    return {
        "hook": f"Nadie te cuenta esto sobre {clean[:80]}…",
        "duration_seconds": 35,
        "format":"9:16",
        "platform":platform,
        "beats":[
            {"t":"0-3s","purpose":"hook","visual":"Primer plano/imagen de alto contraste + texto grande","voice":f"Nadie te cuenta esto sobre {clean[:90]}."},
            {"t":"3-12s","purpose":"setup","visual":"Cambio de plano cada 2-3 s","voice":"Contexto muy breve, sin introducciones largas."},
            {"t":"12-27s","purpose":"payoff","visual":"Tres revelaciones visuales progresivas","voice":"Entrega el dato, giro o mini-historia principal."},
            {"t":"27-35s","purpose":"cta","visual":"Cierre limpio con continuidad visual","voice":"Cierra con una pregunta o llamada a ver la siguiente parte."},
        ],
        "caption": f"{clean[:160]} #historia #reels #tiktok",
        "aigc": True,
    }


def process_one(scope_id):
    task=holdings.next_task(scope_id,"media")
    if not task: return "Media: cola vacía."
    p=task.get("payload") or {}; topic=p.get("topic") or "historia"; platform=p.get("platform") or "tiktok"
    plan=_local_plan(topic,platform)
    # Optional bridge: a user-managed DramaClaw service can accept ZAR's story brief.
    bridge=os.environ.get("DRAMACLAW_CREATE_URL","").strip()
    if bridge:
        try:
            r=requests.post(bridge,json={"source":"ZAR","topic":topic,"platform":platform,"plan":plan,"powered_by":"DramaClaw"},timeout=60)
            if r.ok:
                try: plan["dramaclaw_job"]=r.json()
                except ValueError: plan["dramaclaw_job"]={"response":r.text[:1200]}
        except requests.RequestException as exc:
            plan["dramaclaw_error"]=str(exc)[:400]
    holdings.update_task(scope_id,"media",task["id"],status="READY_FOR_PRODUCTION",result=plan)
    return f"Media: guion/storyboard preparado para {topic[:80]}."


def publish(scope_id, task_id, video_url, platform, caption="", confirmed=False):
    d=holdings.read(scope_id); task=next((x for x in d["companies"]["media"].get("queue",[]) if x.get("id")==task_id),None)
    if not task: raise KeyError("Tarea Media no encontrada.")
    decision=gate("Publicar contenido en red social",{"platform":platform,"video_url":video_url,"task":task},"high")
    if not confirmed:
        return {"ok":False,"requires_review":True,"decision":decision}
    if platform=="tiktok": result=tiktok_direct_post(video_url,caption or ((task.get("result") or {}).get("caption") or ""),confirmed=True)
    elif platform in {"instagram","reels"}: result=instagram_reel(video_url,caption or ((task.get("result") or {}).get("caption") or ""),confirmed=True)
    else: raise ValueError("Plataforma no soportada en este endpoint.")
    holdings.update_task(scope_id,"media",task_id,status="PUBLISHED" if result.get("ok") and not result.get("pending_publish") else "PUBLISHING",result={**(task.get("result") or {}),"publish":result})
    holdings.update_company(scope_id,"media",action=f"Publicación {platform}: {'enviada' if result.get('ok') else 'fallida'}",event="PUBLISH",event_detail=str(result)[:1200])
    return {**result,"decision":decision}



def produce_local(scope_id, task_id):
    """Render an actual vertical MP4 with ZAR's existing Studio/FFmpeg stack.

    This is intentionally deterministic and dependency-light: if no external
    DramaClaw/video provider is configured, ZAR still produces a usable visual
    story from title cards + optional ElevenLabs/Gemini narration.
    """
    d=holdings.read(scope_id)
    task=next((x for x in d["companies"]["media"].get("queue",[]) if x.get("id")==task_id),None)
    if not task: raise KeyError("Tarea Media no encontrada.")
    if task.get("status")=="QUEUED":
        process_one(scope_id)
        d=holdings.read(scope_id); task=next((x for x in d["companies"]["media"].get("queue",[]) if x.get("id")==task_id),task)
    plan=task.get("result") or _local_plan((task.get("payload") or {}).get("topic") or "historia",(task.get("payload") or {}).get("platform") or "tiktok")
    from PIL import Image, ImageDraw, ImageFont
    from .video_creator import create_project, get_project, save_project, MEDIA_DIR, render_project, _normalize_media_item
    from .voice_pro import synthesize
    project=create_project("ZAR Media · "+str((task.get("payload") or {}).get("topic") or "Historia")[:70],"tiktok","dramatic","fade",7.5)
    p=get_project(project["id"])
    beats=plan.get("beats") or []
    palette=[("#09090b","#f4d58d"),("#111827","#f9fafb"),("#1c1917","#fde68a"),("#0c0a09","#f5f5f4")]
    font_path="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    small_path="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    for idx,beat in enumerate(beats[:6] or [{"purpose":"hook","voice":plan.get("hook") or "Historia ZAR"}]):
        bg,fg=palette[idx%len(palette)]
        img=Image.new("RGB",(1080,1920),bg); draw=ImageDraw.Draw(img)
        try:
            font=ImageFont.truetype(font_path,76); small=ImageFont.truetype(small_path,34)
        except Exception:
            font=ImageFont.load_default(); small=font
        headline=str(beat.get("voice") or beat.get("visual") or plan.get("hook") or "Historia")
        lines=textwrap.wrap(headline,width=24)[:7]
        y=520
        for line in lines:
            box=draw.textbbox((0,0),line,font=font); w=box[2]-box[0]
            draw.text(((1080-w)//2,y),line,font=font,fill=fg)
            y+=104
        label=(str(beat.get("purpose") or "ZAR MEDIA").upper()+" · "+str(beat.get("t") or ""))[:80]
        draw.text((70,110),label,font=small,fill=fg)
        draw.text((70,1760),"ZAR MEDIA · AI VISUAL STORY",font=small,fill=fg)
        mid=uuid.uuid4().hex; stored=f"{mid}.png"; path=MEDIA_DIR/stored; img.save(path,"PNG")
        item={"id":mid,"name":f"zar_media_{idx+1}.png","stored_name":stored,"kind":"image","mime":"image/png","size":path.stat().st_size,"duration":None}
        _normalize_media_item(item,len(p.get("media") or [])); item["transition_to_next"]="fade"; item["transition_duration"]=0.3
        p.setdefault("media",[]).append(item)
    narration=" ".join(str(x.get("voice") or "") for x in beats if x.get("voice")).strip()
    provider=None; audio_error=None
    if narration:
        try:
            audio,mime,provider=synthesize(narration,language="es-ES")
            ext=".mp3" if "mpeg" in str(mime) else ".wav"
            apath=MEDIA_DIR/f"{project['id']}_voice{ext}"; apath.write_bytes(audio)
            p["music"]={"path":str(apath),"provider":provider,"kind":"voiceover","mood":"narration"}
            p["audio_track"]={"trim_start":0.0,"trim_end":None,"volume":1.0}
        except Exception as exc:
            audio_error=str(exc)[:500]
    p["editor"]["title"]=plan.get("hook") or project["name"]
    p["editor"]["description"]=plan.get("caption") or ""
    save_project(p)
    rendered=render_project(project["id"],music=bool(p.get("music")))
    preview=rendered.get("preview_url")
    result={**plan,"project_id":project["id"],"preview_url":preview,"download_url":rendered.get("download_url"),"voice_provider":provider,"voice_error":audio_error}
    holdings.update_task(scope_id,"media",task_id,status="PRODUCED",result=result)
    holdings.update_company(scope_id,"media",action=f"MP4 producido · {project['id'][:8]} · voz {provider or 'sin TTS'}",event="PRODUCE",event_detail=preview or "")
    return {"ok":True,"task_id":task_id,"project_id":project["id"],"preview_url":preview,"download_url":rendered.get("download_url"),"caption":plan.get("caption") or "","voice_provider":provider,"voice_error":audio_error}
