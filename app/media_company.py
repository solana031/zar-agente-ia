"""ZAR Media direct production pipeline.

Preferred path: a separately deployed/self-hosted DramaClaw instance receives the
complete master brief and returns (or exposes) a finished vertical video.
Fallback path: ZAR keeps the complete brief, creates a structured shot plan, makes
real 9:16 visual frames with Gemini Image (or reusable Commons imagery), narrates
with the ZAR voice router and composes the final MP4 with the existing Studio stack.
The old text-card renderer is retained only as a final emergency fallback.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import requests
import time
import uuid
import textwrap
from pathlib import Path
from datetime import datetime, timezone

from . import holdings
from .jev_decision import gate
from .social_publish import status as social_status, tiktok_direct_post, instagram_reel
from .config import load as load_config
from .model_router import model_for


def _dramaclaw_base():
    return os.environ.get("DRAMACLAW_API_URL", "").strip().rstrip("/")


def _dramaclaw_create_url():
    return os.environ.get("DRAMACLAW_CREATE_URL", "").strip()


def status():
    base = _dramaclaw_base()
    create = _dramaclaw_create_url()
    return {
        "dramaclaw_bridge_configured": bool(create or base),
        "dramaclaw_direct_configured": bool(create),
        "dramaclaw_api_url": base,
        "dramaclaw_create_url": create,
        "attribution_required": bool(create or base),
        "visual_fallback": "Gemini Image → Wikimedia Commons → graphic card",
        "preferred_provider": "DramaClaw Direct" if create else "ZAR Native Visual",
        "social": social_status(),
        "pipeline": ["MASTER_BRIEF", "SCRIPT", "BEATS", "STORYBOARD", "VISUALS", "VOICE", "EDIT", "QA", "PUBLISH", "ANALYTICS"],
    }


def queue_story(scope_id, topic, goal="retención", platform="tiktok"):
    master_brief = str(topic or "").strip()
    if not master_brief:
        raise ValueError("Falta la historia/briefing.")
    payload = {
        "topic": master_brief,
        "master_brief": master_brief,
        "goal": goal,
        "platform": platform,
        "stage": "MASTER_BRIEF",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "brief_chars": len(master_brief),
    }
    return holdings.queue_task(scope_id, "media", "short_story", payload, requires_approval=False)


def _sentences(text):
    chunks = [x.strip() for x in re.split(r"(?<=[.!?…])\s+|\n+", str(text or "")) if x.strip()]
    return chunks or [str(text or "Historia ZAR").strip()]


def _local_plan(master_brief, platform):
    """Dependency-light plan that preserves the user's story instead of replacing it."""
    clean = re.sub(r"\s+", " ", master_brief).strip()
    sents = _sentences(master_brief)
    # Keep as much original material as possible in six visual beats.
    groups = [[] for _ in range(min(6, max(3, len(sents))))]
    for i, sent in enumerate(sents):
        groups[min(len(groups)-1, int(i * len(groups) / max(1, len(sents))))].append(sent)
    beats = []
    purposes = ["hook", "setup", "escalation", "reveal", "payoff", "cta"]
    total = max(24, min(70, 6 + len(clean) // 35))
    per = max(4, total / max(1, len(groups)))
    for i, group in enumerate(groups):
        voice = " ".join(group).strip() or clean[:260]
        visual_seed = voice[:360]
        beats.append({
            "index": i + 1,
            "purpose": purposes[min(i, len(purposes)-1)],
            "duration_seconds": round(per, 1),
            "voice": voice,
            "visual_prompt": (
                "Cinematic vertical 9:16 story frame, realistic lighting, clear subject, no text, "
                "strong composition, continuity with the previous shot. Scene: " + visual_seed
            ),
            "subtitle": voice[:180],
        })
    return {
        "provider": "ZAR Local Plan",
        "master_brief": master_brief,
        "hook": sents[0][:260],
        "duration_seconds": round(sum(float(x["duration_seconds"]) for x in beats), 1),
        "format": "9:16",
        "platform": platform,
        "style": "cinematic short-form visual storytelling",
        "beats": beats,
        "caption": f"{clean[:220]} #historia #reels #tiktok",
        "aigc": True,
    }


def _extract_json(text):
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return None


def _ai_plan(master_brief, platform):
    """Use ZAR's existing reasoning model to turn the full brief into shot-level JSON."""
    cfg = load_config()
    key = (cfg.get("api", {}).get("api_key") or os.environ.get("GEMINI_API_KEY", "")).strip()
    if not key:
        return _local_plan(master_brief, platform)
    model = model_for("reasoning")
    prompt = f"""You are ZAR Media's short-form film director. Preserve ALL important story facts from MASTER_BRIEF.
Do not replace it with a generic summary. Build a publishable vertical {platform} story.
Return STRICT JSON only with keys: hook, style, duration_seconds, caption, beats.
beats must contain 5-8 objects with: index, purpose, duration_seconds, voice, visual_prompt, subtitle.
voice must narrate the actual story in natural Spanish from Spain; the concatenated voices should preserve the full plot.
visual_prompt must describe a concrete cinematic 9:16 shot with character, setting, action, camera, lighting and continuity; do not ask for on-image text.
Avoid generic instructions like 'change shot' or 'give context'.

MASTER_BRIEF:
{master_brief[:12000]}
"""
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": key},
            headers={"Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.45, "responseMimeType": "application/json"}},
            timeout=120,
        )
        if r.ok:
            data = r.json(); parts = (((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
            text = "\n".join(str(p.get("text") or "") for p in parts if p.get("text"))
            parsed = _extract_json(text)
            if isinstance(parsed, dict) and isinstance(parsed.get("beats"), list) and len(parsed["beats"]) >= 3:
                parsed["provider"] = f"ZAR Director/{model}"
                parsed["master_brief"] = master_brief
                parsed["platform"] = platform
                parsed["format"] = "9:16"
                parsed["aigc"] = True
                for i, beat in enumerate(parsed["beats"][:8]):
                    beat.setdefault("index", i + 1)
                    beat.setdefault("purpose", "scene")
                    beat.setdefault("duration_seconds", max(4, float(parsed.get("duration_seconds") or 36) / max(1, len(parsed["beats"]))))
                    beat.setdefault("voice", "")
                    beat.setdefault("subtitle", str(beat.get("voice") or "")[:180])
                    beat.setdefault("visual_prompt", str(beat.get("voice") or master_brief[:300]))
                parsed["beats"] = parsed["beats"][:8]
                return parsed
    except Exception:
        pass
    return _local_plan(master_brief, platform)


def _headers_for_dramaclaw():
    h = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "ZAR-Media/33.1.1"}
    token = os.environ.get("DRAMACLAW_API_TOKEN", "").strip()
    if token:
        h["Authorization"] = "Bearer " + token
    return h


def _find_video_url(obj):
    """Accept common bridge result shapes without hard-coding one hosted wrapper."""
    if isinstance(obj, str) and obj.startswith(("http://", "https://")) and re.search(r"\.(mp4|mov|webm)(?:\?|$)", obj, re.I):
        return obj
    if isinstance(obj, dict):
        for k in ("video_url", "preview_url", "download_url", "mp4_url", "output_url", "url"):
            v = obj.get(k)
            if isinstance(v, str) and v.startswith(("http://", "https://")):
                return v
        for v in obj.values():
            found = _find_video_url(v)
            if found:
                return found
    if isinstance(obj, list):
        for v in obj:
            found = _find_video_url(v)
            if found:
                return found
    return None


def _submit_dramaclaw(master_brief, platform, plan, prior_job=None):
    create_url = _dramaclaw_create_url()
    if not create_url:
        return None
    payload = {
        "source": "ZAR Media",
        "powered_by": "DramaClaw",
        "master_brief": master_brief,
        "manuscript": master_brief,
        "platform": platform,
        "aspect_ratio": "9:16",
        "deliverable": "mp4",
        "plan": plan,
        "include_assets": True,
        "language": "es-ES",
    }
    if prior_job:
        payload["prior_job"] = prior_job
    try:
        r = requests.post(create_url, json=payload, headers=_headers_for_dramaclaw(), timeout=120)
        if not r.ok:
            return {"ok": False, "error": f"DramaClaw HTTP {r.status_code}: {r.text[:800]}"}
        try:
            data = r.json()
        except ValueError:
            data = {"response": r.text[:4000]}
        result = {"ok": True, "job": data, "provider": "DramaClaw Direct"}
        direct = _find_video_url(data)
        if direct:
            result["video_url"] = direct
            return result
        status_url = data.get("status_url") if isinstance(data, dict) else None
        if isinstance(status_url, str) and status_url.startswith(("http://", "https://")):
            for _ in range(8):
                time.sleep(2.5)
                sr = requests.get(status_url, headers=_headers_for_dramaclaw(), timeout=30)
                if not sr.ok:
                    break
                try:
                    sd = sr.json()
                except ValueError:
                    break
                direct = _find_video_url(sd)
                if direct:
                    result["job"] = sd
                    result["video_url"] = direct
                    return result
                if str(sd.get("status") or "").lower() in {"failed", "error", "cancelled"}:
                    result["error"] = str(sd.get("error") or "DramaClaw falló")[:800]
                    break
        return result
    except requests.RequestException as exc:
        return {"ok": False, "error": str(exc)[:800], "provider": "DramaClaw Direct"}


def process_one(scope_id):
    task = holdings.next_task(scope_id, "media")
    if not task:
        return "Media: cola vacía."
    p = task.get("payload") or {}
    master_brief = str(p.get("master_brief") or p.get("topic") or "historia").strip()
    platform = p.get("platform") or "tiktok"
    plan = _ai_plan(master_brief, platform)
    dc = _submit_dramaclaw(master_brief, platform, plan)
    if dc:
        plan["dramaclaw"] = dc
        if dc.get("video_url"):
            plan["production_provider"] = "DramaClaw Direct"
            plan["preview_url"] = dc["video_url"]
    holdings.update_task(scope_id, "media", task["id"], status="READY_FOR_PRODUCTION", result=plan)
    return f"Media: plan preparado; briefing íntegro conservado ({len(master_brief)} caracteres); {len(plan.get('beats') or [])} escenas preparadas."


def publish(scope_id, task_id, video_url, platform, caption="", confirmed=False):
    d = holdings.read(scope_id); task = next((x for x in d["companies"]["media"].get("queue", []) if x.get("id") == task_id), None)
    if not task:
        raise KeyError("Tarea Media no encontrada.")
    decision = gate("Publicar contenido en red social", {"platform": platform, "video_url": video_url, "task": task}, "high")
    if not confirmed:
        return {"ok": False, "requires_review": True, "decision": decision}
    if platform == "tiktok":
        result = tiktok_direct_post(video_url, caption or ((task.get("result") or {}).get("caption") or ""), confirmed=True)
    elif platform in {"instagram", "reels"}:
        result = instagram_reel(video_url, caption or ((task.get("result") or {}).get("caption") or ""), confirmed=True)
    else:
        raise ValueError("Plataforma no soportada en este endpoint.")
    holdings.update_task(scope_id, "media", task_id, status="PUBLISHED" if result.get("ok") and not result.get("pending_publish") else "PUBLISHING", result={**(task.get("result") or {}), "publish": result})
    holdings.update_company(scope_id, "media", action=f"Publicación {platform}: {'enviada' if result.get('ok') else 'fallida'}", event="PUBLISH", event_detail=str(result)[:1200])
    return {**result, "decision": decision}


def _gemini_image(prompt):
    cfg = load_config()
    key = (cfg.get("api", {}).get("api_key") or os.environ.get("GEMINI_API_KEY", "")).strip()
    if not key:
        raise RuntimeError("Sin GEMINI_API_KEY para generar escenas.")
    model = model_for("image")
    body = {
        "contents": [{"parts": [{"text": str(prompt or "")[:5000]}]}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": key}, headers={"Content-Type": "application/json"}, json=body, timeout=150,
    )
    if not r.ok:
        raise RuntimeError(f"Gemini Image HTTP {r.status_code}: {r.text[:500]}")
    data = r.json(); parts = (((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
    for part in parts:
        inline = part.get("inlineData") or part.get("inline_data") if isinstance(part, dict) else None
        if inline and inline.get("data"):
            return base64.b64decode(inline["data"]), inline.get("mimeType") or inline.get("mime_type") or "image/png", f"Gemini Image/{model}"
    raise RuntimeError("Gemini Image no devolvió imagen.")


def _commons_image(query):
    from .web_search import search_reusable_images
    out = search_reusable_images(query, limit=4)
    for item in out.get("results") or []:
        url = item.get("image_url")
        if not url:
            continue
        try:
            r = requests.get(url, timeout=35, headers={"User-Agent": "ZAR-Media/33.1.1"})
            if r.ok and r.content:
                return r.content, (r.headers.get("Content-Type") or "image/jpeg").split(";")[0], "Wikimedia Commons", item
        except requests.RequestException:
            continue
    raise RuntimeError("Sin imagen reutilizable disponible.")


def _fit_vertical(raw):
    from PIL import Image, ImageEnhance
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    target = 1080 / 1920
    ratio = img.width / max(1, img.height)
    if ratio > target:
        nw = int(img.height * target); left = max(0, (img.width - nw) // 2); img = img.crop((left, 0, left + nw, img.height))
    else:
        nh = int(img.width / target); top = max(0, (img.height - nh) // 2); img = img.crop((0, top, img.width, top + nh))
    img = img.resize((1080, 1920), Image.LANCZOS)
    img = ImageEnhance.Contrast(img).enhance(1.05)
    out = io.BytesIO(); img.save(out, "JPEG", quality=92)
    return out.getvalue()


def _graphic_fallback(beat, idx):
    from PIL import Image, ImageDraw, ImageFont
    # Not black: create a warm cinematic gradient/shape card as last-resort only.
    w, h = 1080, 1920
    img = Image.new("RGB", (w, h), (22 + (idx * 9) % 35, 17, 20 + (idx * 13) % 35))
    draw = ImageDraw.Draw(img, "RGBA")
    for n in range(10):
        x = (n * 137 + idx * 71) % w; y = (n * 223 + idx * 113) % h
        r = 110 + (n * 31) % 240
        draw.ellipse((x-r, y-r, x+r, y+r), fill=(180, 95 + (n*11)%80, 40 + (n*17)%80, 24))
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 54)
        small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 26)
    except Exception:
        font = ImageFont.load_default(); small = font
    title = str(beat.get("subtitle") or beat.get("voice") or "ZAR Media")
    lines = textwrap.wrap(title, width=30)[:6]
    y = 1320
    draw.rounded_rectangle((55, y-65, 1025, min(1865, y + len(lines)*74 + 70)), 34, fill=(0,0,0,145))
    for line in lines:
        draw.text((95, y), line, font=font, fill=(255,244,225,245)); y += 72
    draw.text((95, 1780), "ZAR MEDIA · FALLBACK VISUAL", font=small, fill=(233,194,124,210))
    out = io.BytesIO(); img.save(out, "JPEG", quality=90); return out.getvalue(), "Graphic fallback", None


def _make_scene_frame(beat, idx, style, master_brief):
    prompt = (
        f"Create ONE cinematic vertical 9:16 frame for a short-form story. Style: {style}. "
        "No captions, no logos, no text in the image. Maintain believable continuity and visual storytelling. "
        f"SHOT {idx+1}: {beat.get('visual_prompt') or beat.get('voice')}. "
        f"Story context: {master_brief[:1800]}"
    )
    errors = []
    try:
        raw, mime, provider = _gemini_image(prompt)
        return _fit_vertical(raw), provider, None
    except Exception as exc:
        errors.append(str(exc)[:240])
    try:
        q = str(beat.get("visual_prompt") or beat.get("voice") or master_brief)[:220]
        raw, mime, provider, meta = _commons_image(q)
        return _fit_vertical(raw), provider, {"source": meta}
    except Exception as exc:
        errors.append(str(exc)[:240])
    raw, provider, meta = _graphic_fallback(beat, idx)
    return raw, provider, {"errors": errors}


def produce_local(scope_id, task_id):
    """Produce via DramaClaw when it already returned a final film; otherwise render real visual scenes in ZAR."""
    d = holdings.read(scope_id)
    task = next((x for x in d["companies"]["media"].get("queue", []) if x.get("id") == task_id), None)
    if not task:
        raise KeyError("Tarea Media no encontrada.")
    if task.get("status") == "QUEUED":
        process_one(scope_id)
        d = holdings.read(scope_id); task = next((x for x in d["companies"]["media"].get("queue", []) if x.get("id") == task_id), task)
    payload = task.get("payload") or {}
    master_brief = str(payload.get("master_brief") or payload.get("topic") or "Historia").strip()
    platform = payload.get("platform") or "tiktok"
    plan = task.get("result") or _ai_plan(master_brief, platform)

    # If process_one got a completed DramaClaw film, use it directly.
    dc = plan.get("dramaclaw") if isinstance(plan, dict) else None
    if not (isinstance(dc, dict) and dc.get("video_url")) and _dramaclaw_create_url():
        dc = _submit_dramaclaw(master_brief, platform, plan, prior_job=(dc or {}).get("job") if isinstance(dc, dict) else None)
        if dc:
            plan["dramaclaw"] = dc
    if isinstance(dc, dict) and dc.get("video_url"):
        result = {**plan, "production_provider": "DramaClaw Direct", "preview_url": dc["video_url"], "download_url": dc["video_url"], "voice_provider": "DramaClaw", "visual_providers": ["DramaClaw Direct"]}
        holdings.update_task(scope_id, "media", task_id, status="PRODUCED", result=result)
        holdings.update_company(scope_id, "media", action="MP4 producido por DramaClaw Direct", event="PRODUCE", event_detail=dc["video_url"])
        return {"ok": True, "task_id": task_id, "preview_url": dc["video_url"], "download_url": dc["video_url"], "caption": plan.get("caption") or "", "voice_provider": "DramaClaw", "visual_provider": "DramaClaw Direct", "production_provider": "DramaClaw Direct", "brief_chars": len(master_brief)}

    from .video_creator import create_project, get_project, save_project, MEDIA_DIR, render_project, _normalize_media_item
    from .voice_pro import synthesize

    project = create_project("ZAR Media · " + master_brief[:70], "tiktok", "dramatic", "fade", 5.8)
    p = get_project(project["id"])
    beats = (plan.get("beats") or [])[:8]
    if not beats:
        beats = _local_plan(master_brief, platform)["beats"]
    visual_providers = []
    visual_details = []
    for idx, beat in enumerate(beats):
        raw, provider, meta = _make_scene_frame(beat, idx, str(plan.get("style") or "cinematic realism"), master_brief)
        visual_providers.append(provider)
        if meta:
            visual_details.append({"scene": idx+1, "provider": provider, **meta})
        mid = uuid.uuid4().hex; stored = f"{mid}.jpg"; path = MEDIA_DIR / stored; path.write_bytes(raw)
        item = {"id": mid, "name": f"zar_media_scene_{idx+1}.jpg", "stored_name": stored, "kind": "image", "mime": "image/jpeg", "size": path.stat().st_size, "duration": None}
        _normalize_media_item(item, len(p.get("media") or []))
        item["transition_to_next"] = "fade"; item["transition_duration"] = 0.35
        item["caption"] = str(beat.get("subtitle") or beat.get("voice") or "")[:260]
        p.setdefault("media", []).append(item)

    narration = " ".join(str(x.get("voice") or "").strip() for x in beats if str(x.get("voice") or "").strip()).strip()
    if not narration:
        narration = master_brief
    provider = None; audio_error = None
    if narration:
        try:
            audio, mime, provider = synthesize(narration, language="es-ES")
            ext = ".mp3" if "mpeg" in str(mime) else ".wav"
            apath = MEDIA_DIR / f"{project['id']}_voice{ext}"; apath.write_bytes(audio)
            p["music"] = {"path": str(apath), "provider": provider, "kind": "voiceover", "mood": "narration"}
            p["audio_track"] = {"trim_start": 0.0, "trim_end": None, "volume": 1.0}
        except Exception as exc:
            audio_error = str(exc)[:500]

    p["editor"]["title"] = plan.get("hook") or master_brief[:120]
    p["editor"]["description"] = plan.get("caption") or ""
    p["editor"]["auto_caption"] = True
    p["editor"]["viral_mode"] = True
    save_project(p)
    rendered = render_project(project["id"], music=bool(p.get("music")))
    preview = rendered.get("preview_url")
    primary_visual = " + ".join(dict.fromkeys(visual_providers))
    result = {**plan, "master_brief": master_brief, "project_id": project["id"], "preview_url": preview, "download_url": rendered.get("download_url"), "voice_provider": provider, "voice_error": audio_error, "visual_provider": primary_visual, "visual_providers": visual_providers, "visual_details": visual_details, "production_provider": "ZAR Native Visual"}
    holdings.update_task(scope_id, "media", task_id, status="PRODUCED", result=result)
    holdings.update_company(scope_id, "media", action=f"MP4 visual producido · {project['id'][:8]} · visual {primary_visual[:80]} · voz {provider or 'sin TTS'}", event="PRODUCE", event_detail=preview or "")
    return {"ok": True, "task_id": task_id, "project_id": project["id"], "preview_url": preview, "download_url": rendered.get("download_url"), "caption": plan.get("caption") or "", "voice_provider": provider, "voice_error": audio_error, "visual_provider": primary_visual, "production_provider": "ZAR Native Visual", "brief_chars": len(master_brief), "scenes": len(beats)}
