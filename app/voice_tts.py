import base64
import io
import os
import wave
import requests

from .config import load
from .model_router import model_for


def _api_key():
    cfg = load()
    return (cfg.get('api', {}).get('api_key') or os.environ.get('GEMINI_API_KEY', '')).strip()


def synthesize(text: str, voice: str = 'Kore', language: str = 'es-ES'):
    text = str(text or '').strip()
    if not text:
        raise RuntimeError('No hay texto para sintetizar.')
    if len(text) > 12000:
        text = text[:12000]
    key = _api_key()
    if not key:
        raise RuntimeError('Falta la API key de Gemini para TTS.')

    model = model_for('tts')
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
    prompt = f'Lee en español de España, con naturalidad y sin añadir contenido: {text}'
    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {
            'responseModalities': ['AUDIO'],
            'speechConfig': {
                'voiceConfig': {
                    'prebuiltVoiceConfig': {'voiceName': voice or 'Kore'}
                }
            }
        }
    }
    r = requests.post(
        url,
        headers={'x-goog-api-key': key, 'Content-Type': 'application/json'},
        json=payload,
        timeout=120,
    )
    if not r.ok:
        raise RuntimeError(f'Gemini TTS HTTP {r.status_code}: {r.text[:800]}')
    data = r.json()
    parts = (((data.get('candidates') or [{}])[0].get('content') or {}).get('parts') or [])
    audio_b64 = ''
    mime = 'audio/pcm;rate=24000'
    for part in parts:
        inline = part.get('inlineData') if isinstance(part, dict) else None
        if inline and inline.get('data'):
            audio_b64 = inline['data']
            mime = inline.get('mimeType') or mime
            break
    if not audio_b64:
        raise RuntimeError(f'Gemini TTS no devolvió audio: {str(data)[:900]}')

    pcm = base64.b64decode(audio_b64)
    rate = 24000
    if 'rate=' in mime:
        try:
            rate = int(mime.split('rate=')[1].split(';')[0])
        except Exception:
            pass
    wav = io.BytesIO()
    with wave.open(wav, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return wav.getvalue(), 'audio/wav'
