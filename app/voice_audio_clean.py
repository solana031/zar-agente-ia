import os
import subprocess
import tempfile


def _ffmpeg_exe():
    """Resolve an ffmpeg binary without requiring a system installation."""
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        return get_ffmpeg_exe()
    except Exception:
        return os.environ.get("FFMPEG_BINARY", "ffmpeg")


def clean_audio(raw: bytes, source_ext: str = ".webm"):
    """
    Convert browser audio to a stable mono 16 kHz WAV and suppress steady
    background noise before sending it to the transcription model.

    Returns (wav_bytes, mime_type). If ffmpeg is unavailable or conversion
    fails, the caller can safely fall back to the original browser audio.
    """
    if not raw:
        return raw, "audio/webm"

    ffmpeg = _ffmpeg_exe()
    with tempfile.TemporaryDirectory(prefix="zar_voice_") as td:
        src = os.path.join(td, "input" + (source_ext if source_ext.startswith(".") else ".webm"))
        dst = os.path.join(td, "clean.wav")
        with open(src, "wb") as f:
            f.write(raw)

        # Keep the speech band while removing low rumble / high-frequency hiss.
        # afftdn is deliberately moderate: the goal is noise reduction, not
        # aggressive denoising that could distort consonants and names.
        cmd = [
            ffmpeg,
            "-hide_banner", "-loglevel", "error",
            "-y", "-i", src,
            "-vn",
            "-af", "highpass=f=90,lowpass=f=9000,afftdn=nf=-24",
            "-ac", "1",
            "-ar", "16000",
            "-c:a", "pcm_s16le",
            dst,
        ]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45)
            with open(dst, "rb") as f:
                cleaned = f.read()
            if cleaned:
                return cleaned, "audio/wav"
        except Exception:
            pass

    return raw, "audio/webm"
