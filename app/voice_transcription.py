import base64
import os
import re
import uuid

import requests

from .config import load
from .model_router import model_for
from .voice_audio_clean import clean_audio


GEMINI_BASE = 'https://generativelanguage.googleapis.com'


def _clean_transcript(text: str) -> str:
    text = str(text or '').strip()
    text = re.sub(r'^```(?:text|txt)?\s*', '', text, flags=re.I)
    text = re.sub(r'\s*```$', '', text).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
        text = text[1:-1].strip()
    return text


def _extract_generate_text(data):
    candidates = data.get('candidates') or []
    if not candidates:
        return ''
    content = candidates[0].get('content') or {}
    parts = content.get('parts') or []

    transcripts = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        audio_transcription = part.get('audioTranscription')
        if isinstance(audio_transcription, dict):
            value = audio_transcription.get('text') or audio_transcription.get('transcript')
            if value:
                transcripts.append(str(value))
                continue
        value = part.get('text')
        if value is not None:
            transcripts.append(str(value))

    return _clean_transcript(''.join(transcripts))


def _upload_file(key, audio_bytes, mime, display_name):
    """Upload audio through Gemini Files API and return (file_name, file_uri)."""
    start_url = f'{GEMINI_BASE}/upload/v1beta/files'
    headers = {
        'x-goog-api-key': key,
        'X-Goog-Upload-Protocol': 'resumable',
        'X-Goog-Upload-Command': 'start',
        'X-Goog-Upload-Header-Content-Length': str(len(audio_bytes)),
        'X-Goog-Upload-Header-Content-Type': mime,
        'Content-Type': 'application/json',
    }
    metadata = {'file': {'display_name': display_name or f'zar-voice-{uuid.uuid4().hex[:8]}'}}
    r = requests.post(start_url, headers=headers, json=metadata, timeout=30)
    if not r.ok:
        raise RuntimeError(f'Gemini Files start HTTP {r.status_code}: {r.text[:700]}')

    upload_url = r.headers.get('x-goog-upload-url') or r.headers.get('X-Goog-Upload-URL')
    if not upload_url:
        raise RuntimeError('Gemini Files no devolvió la URL de subida.')

    upload_headers = {
        'x-goog-api-key': key,
        'Content-Length': str(len(audio_bytes)),
        'X-Goog-Upload-Offset': '0',
        'X-Goog-Upload-Command': 'upload, finalize',
    }
    u = requests.post(upload_url, headers=upload_headers, data=audio_bytes, timeout=120)
    if not u.ok:
        raise RuntimeError(f'Gemini Files upload HTTP {u.status_code}: {u.text[:700]}')

    try:
        info = u.json()
    except Exception:
        raise RuntimeError(f'Gemini Files devolvió una respuesta no válida: {u.text[:500]}')

    file_info = info.get('file') or info
    file_name = file_info.get('name') or ''
    file_uri = file_info.get('uri') or ''
    if not file_uri:
        raise RuntimeError(f'Gemini Files no devolvió file.uri: {str(info)[:700]}')
    return file_name, file_uri


def _delete_file(key, file_name):
    if not file_name:
        return
    try:
        requests.delete(
            f'{GEMINI_BASE}/v1beta/{file_name}',
            headers={'x-goog-api-key': key},
            timeout=20,
        )
    except Exception:
        pass


def _extract_interaction_text(data):
    """Extract transcription text from current Gemini Interactions responses."""
    if not isinstance(data, dict):
        return ''

    direct = data.get('output_text') or data.get('text')
    if isinstance(direct, str) and direct.strip():
        return _clean_transcript(direct)

    chunks = []

    # Current Interactions responses can expose model output in steps[].content[].
    for step in data.get('steps') or []:
        if not isinstance(step, dict):
            continue
        for content in step.get('content') or []:
            if not isinstance(content, dict):
                continue
            value = content.get('text')
            if isinstance(value, str) and value.strip():
                chunks.append(value)
            # Some response variants nest text in parts.
            for part in content.get('parts') or []:
                if isinstance(part, dict):
                    value = part.get('text')
                    if isinstance(value, str) and value.strip():
                        chunks.append(value)

    # Compatibility with output/output items in other Interactions responses.
    for output in data.get('outputs') or []:
        if not isinstance(output, dict):
            continue
        value = output.get('text')
        if isinstance(value, str) and value.strip():
            chunks.append(value)
        for content in output.get('content') or []:
            if isinstance(content, dict):
                value = content.get('text')
                if isinstance(value, str) and value.strip():
                    chunks.append(value)

    return _clean_transcript(''.join(chunks))


def _interactions_transcribe(key, audio_bytes, mime, prompt):
    """Use Gemini 3.5 Transcribe through the documented Files + Interactions flow."""
    file_name, file_uri = _upload_file(key, audio_bytes, mime, 'ZAR voice transcription')
    try:
        url = f'{GEMINI_BASE}/v1beta/interactions'

        # Gemini 3.5 Transcribe is documented as an audio-only interaction.
        # The transcription instructions belong in transcription_config rather
        # than as an additional text input item.
        payload = {
            'model': model_for('transcribe'),
            'input': [
                {
                    'type': 'audio',
                    'uri': file_uri,
                    'mime_type': mime,
                },
            ],
            'generation_config': {
                'transcription_config': {
                    'language_codes': ['es-ES'],
                    'mode': {'type': 'verbatim'},
                },
            },
        }

        r = requests.post(
            url,
            headers={'x-goog-api-key': key, 'Content-Type': 'application/json'},
            json=payload,
            timeout=120,
        )
        if not r.ok:
            raise RuntimeError(f'Gemini Interactions HTTP {r.status_code}: {r.text[:900]}')

        try:
            data = r.json()
        except Exception:
            raise RuntimeError(f'Gemini Interactions devolvió una respuesta no válida: {r.text[:700]}')

        text = _extract_interaction_text(data)
        if not text:
            raise RuntimeError(f'Gemini Transcribe no devolvió texto: {str(data)[:1600]}')
        return text
    finally:
        _delete_file(key, file_name)


def _generate_content(base_url, model, key, encoded, mime, prompt):
    base = (base_url or f'{GEMINI_BASE}/v1beta').rstrip('/')
    if base.endswith('/openai'):
        base = base[:-6]
    if base.endswith('/v1beta'):
        direct_base = base
    else:
        direct_base = base + '/v1beta'
    url = f'{direct_base}/models/{model}:generateContent'
    payload = {
        'contents': [{
            'role': 'user',
            'parts': [
                {'text': prompt},
                {'inlineData': {'mimeType': mime, 'data': encoded}},
            ],
        }],
        'generationConfig': {
            'temperature': 0,
            'maxOutputTokens': 2048,
        },
    }
    r = requests.post(
        url,
        headers={'x-goog-api-key': key, 'Content-Type': 'application/json'},
        json=payload,
        timeout=120,
    )
    if not r.ok:
        raise RuntimeError(f'Gemini HTTP {r.status_code}: {r.text[:900]}')
    try:
        data = r.json()
    except Exception:
        raise RuntimeError(f'Gemini devolvió una respuesta no válida: {r.text[:500]}')
    text = _extract_generate_text(data)
    if text:
        return text
    raise RuntimeError(f'Gemini no devolvió texto de transcripción: {str(data)[:900]}')


def transcribe_audio(stream, mime_type: str = 'audio/webm', filename: str = 'voz.webm'):
    cfg = load()
    key = (cfg.get('api', {}).get('api_key') or os.environ.get('GEMINI_API_KEY', '')).strip()
    configured_model = (cfg.get('api', {}).get('model') or os.environ.get('ZAR_API_MODEL') or 'gemini-3.6-flash').strip()
    base_url = cfg.get('api', {}).get('base_url') or os.environ.get('ZAR_API_BASE_URL') or f'{GEMINI_BASE}/v1beta/openai'
    if not key:
        raise RuntimeError('Falta la API key de Gemini para la transcripción de voz.')

    raw = stream.read()
    if not raw:
        raise RuntimeError('El audio recibido está vacío.')
    if len(raw) > 25 * 1024 * 1024:
        raise RuntimeError('La grabación de voz es demasiado grande.')

    cleaned, cleaned_mime = clean_audio(raw, os.path.splitext(filename or '')[1] or '.webm')
    encoded = base64.b64encode(cleaned).decode('ascii')
    audio_mime = cleaned_mime or 'audio/wav'

    prompt = (
        'Transcribe este audio en español de forma VERBATIM. Devuelve únicamente el texto que la persona ha pronunciado. '
        'No respondas a la petición, no la resumas y no la reinterpretes. No añadas palabras que no estén en el audio. '
        'Ignora ruido de fondo, música, televisión, conversaciones ajenas, golpes, viento, ventiladores y artefactos del micrófono. '
        'Si una palabra o frase parece repetirse por ruido, eco o un artefacto del micrófono, escríbela una sola vez. '
        'Solo conserva una repetición si la persona realmente la pronuncia. Conserva nombres propios, números, marcas, direcciones, '
        'comandos y palabras coloquiales. Mantén muletillas si se oyen. Si algo es realmente inaudible, no lo inventes. '
        'SOLO TRANSCRIBE EL AUDIO.'
    )

    errors = []

    # Primary path: current Interactions API + Files API, which is the documented
    # path for Gemini 3.5 Transcribe and returns output_text.
    try:
        text = _interactions_transcribe(key, cleaned, audio_mime, prompt)
        return {'text': text, 'provider': 'Gemini 3.5 Transcribe · Interactions API'}
    except Exception as exc:
        errors.append(f'Transcribe Interactions: {str(exc)[:900]}')

    # Compatibility path: legacy generateContent with inline audio.
    try:
        text = _generate_content(
            f'{GEMINI_BASE}/v1beta',
            model_for('transcribe'),
            key,
            encoded,
            audio_mime,
            prompt,
        )
        return {'text': text, 'provider': 'Gemini 3.5 Transcribe · GenerateContent'}
    except Exception as exc:
        errors.append(f'Transcribe GenerateContent: {str(exc)[:900]}')

    # Final fallback to the configured multimodal Gemini model.
    try:
        model_name = configured_model.split('/')[-1]
        text = _generate_content(
            base_url,
            model_name,
            key,
            encoded,
            audio_mime,
            prompt,
        )
        return {'text': text, 'provider': 'Gemini multimodal fallback'}
    except Exception as exc:
        errors.append(f'Fallback: {str(exc)[:900]}')

    raise RuntimeError('No se pudo transcribir el audio. ' + ' | '.join(errors))
