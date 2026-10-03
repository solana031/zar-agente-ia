"""ZAR voice router.

Order for TTS: ElevenLabs -> optional F5-TTS service -> Gemini TTS.
F5-TTS is intentionally an adapter rather than a heavy mandatory Railway
package; point F5_TTS_API_URL at a self-hosted F5-TTS HTTP service.
STT keeps the existing faster-whisper/Gemini routing.
"""
from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path

import requests

from .voice_tts import synthesize as gemini_synthesize
from .voice_transcription import transcribe_audio as gemini_transcribe


def _eleven_configured():
    return bool(os.environ.get("ELEVENLABS_API_KEY", "").strip() and os.environ.get("ELEVENLABS_VOICE_ID", "").strip())


def _f5_url():
    return os.environ.get("F5_TTS_API_URL", "").strip().rstrip("/")


def status():
    try:
        import faster_whisper  # noqa: F401
        fw = True
    except Exception:
        fw = False
    if _eleven_configured():
        tts = "ElevenLabs"
    elif _f5_url():
        tts = "F5-TTS"
    else:
        tts = "Gemini"
    return {
        "tts": tts,
        "tts_chain": ["ElevenLabs", "F5-TTS", "Gemini"],
        "elevenlabs_configured": _eleven_configured(),
        "f5_tts_configured": bool(_f5_url()),
        "f5_tts_url": _f5_url(),
        "faster_whisper_available": fw,
        "stt": "faster-whisper" if fw and os.environ.get("ZAR_STT_PROVIDER", "").lower() in {"faster-whisper", "faster_whisper"} else "Gemini",
    }


def _eleven_synthesize(text):
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "").strip()
    if not (key and voice_id):
        return None
    model = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2").strip()
    def fenv(name, default):
        try: return float(os.environ.get(name, str(default)))
        except Exception: return float(default)
    voice_settings = {
        "stability": max(0.0, min(1.0, fenv("ELEVENLABS_STABILITY", 0.42))),
        "similarity_boost": max(0.0, min(1.0, fenv("ELEVENLABS_SIMILARITY", 0.82))),
        "style": max(0.0, min(1.0, fenv("ELEVENLABS_STYLE", 0.42))),
        "use_speaker_boost": os.environ.get("ELEVENLABS_SPEAKER_BOOST", "1").lower() not in {"0", "false", "no"},
    }
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        params={"output_format": "mp3_44100_128"},
        headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
        json={"text": str(text or "")[:12000], "model_id": model, "voice_settings": voice_settings}, timeout=150,
    )
    if r.ok and r.content:
        return r.content, "audio/mpeg", f"ElevenLabs/{model}"
    return None


def _f5_synthesize(text, language="es-ES"):
    url = _f5_url()
    if not url:
        return None
    endpoint = url if url.rstrip("/").endswith("/tts") else url + "/tts"
    headers = {"Content-Type": "application/json", "Accept": "audio/mpeg, audio/wav, application/json"}
    token = os.environ.get("F5_TTS_API_TOKEN", "").strip()
    if token:
        headers["Authorization"] = "Bearer " + token
    payload = {
        "text": str(text or "")[:12000],
        "language": language,
        "speed": float(os.environ.get("F5_TTS_SPEED", "1.0") or 1.0),
        "reference_audio": os.environ.get("F5_TTS_REFERENCE_AUDIO", "").strip() or None,
        "reference_text": os.environ.get("F5_TTS_REFERENCE_TEXT", "").strip() or None,
    }
    r = requests.post(endpoint, json=payload, headers=headers, timeout=180)
    if not r.ok:
        return None
    ct = (r.headers.get("Content-Type") or "").lower()
    if ct.startswith("audio/") and r.content:
        return r.content, ct.split(";")[0], "F5-TTS"
    try:
        data = r.json()
    except ValueError:
        return None
    b64 = data.get("audio_base64") or data.get("audio")
    if isinstance(b64, str) and len(b64) > 100:
        try:
            return base64.b64decode(b64), data.get("mime") or "audio/wav", "F5-TTS"
        except Exception:
            pass
    audio_url = data.get("audio_url") or data.get("url")
    if isinstance(audio_url, str) and audio_url.startswith(("http://", "https://")):
        rr = requests.get(audio_url, timeout=90)
        if rr.ok and rr.content:
            return rr.content, (rr.headers.get("Content-Type") or "audio/wav").split(";")[0], "F5-TTS"
    return None


def synthesize(text, voice="Kore", language="es-ES"):
    try:
        got = _eleven_synthesize(text)
        if got:
            return got
    except Exception:
        pass
    try:
        got = _f5_synthesize(text, language=language)
        if got:
            return got
    except Exception:
        pass
    audio, mime = gemini_synthesize(text, voice=voice, language=language)
    return audio, mime, "Gemini"


def transcribe(stream, mime="audio/webm", filename="voz.webm"):
    provider = os.environ.get("ZAR_STT_PROVIDER", "").strip().lower()
    if provider in {"faster-whisper", "faster_whisper"}:
        try:
            from faster_whisper import WhisperModel
            raw = stream.read()
            suffix = Path(filename or "audio.webm").suffix or ".webm"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(raw); path = tmp.name
            try:
                size = os.environ.get("ZAR_FASTER_WHISPER_MODEL", "small").strip()
                model = WhisperModel(size, device="cpu", compute_type="int8")
                segments, info = model.transcribe(path, language="es", vad_filter=True, beam_size=3)
                text = " ".join(seg.text.strip() for seg in segments if seg.text.strip()).strip()
                if text:
                    return {"text": text, "provider": f"faster-whisper/{size}", "language": getattr(info, "language", "es")}
            finally:
                try: os.unlink(path)
                except OSError: pass
        except Exception:
            try: stream.seek(0)
            except Exception: pass
    return gemini_transcribe(stream, mime, filename)
