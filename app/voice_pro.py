"""Optional voice providers for ZAR.

ElevenLabs is preferred for TTS when configured.  Existing Gemini TTS remains a
zero-migration fallback.  faster-whisper is an optional local STT integration:
if the package is absent ZAR continues using its current Gemini transcriber.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import requests

from .voice_tts import synthesize as gemini_synthesize
from .voice_transcription import transcribe_audio as gemini_transcribe


def status():
    try:
        import faster_whisper  # noqa: F401
        fw = True
    except Exception:
        fw = False
    return {
        "tts": "ElevenLabs" if os.environ.get("ELEVENLABS_API_KEY", "").strip() and os.environ.get("ELEVENLABS_VOICE_ID", "").strip() else "Gemini",
        "elevenlabs_configured": bool(os.environ.get("ELEVENLABS_API_KEY", "").strip() and os.environ.get("ELEVENLABS_VOICE_ID", "").strip()),
        "faster_whisper_available": fw,
        "stt": "faster-whisper" if fw and os.environ.get("ZAR_STT_PROVIDER", "").lower() in {"faster-whisper","faster_whisper"} else "Gemini",
    }


def synthesize(text, voice="Kore", language="es-ES"):
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "").strip()
    if key and voice_id:
        model = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2").strip()
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            params={"output_format": "mp3_44100_128"},
            headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
            json={"text": str(text or "")[:12000], "model_id": model}, timeout=120,
        )
        if r.ok and r.content:
            return r.content, "audio/mpeg", "ElevenLabs"
        # Never break voice because ElevenLabs is temporarily unavailable.
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
