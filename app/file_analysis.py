import base64
import json
import mimetypes
import os
import re
from pathlib import Path
import requests

from .config import load
from .file_store import get_file, update_file, files_dir, public_item


def _gemini_root(base_url: str) -> str:
    base = (base_url or "https://generativelanguage.googleapis.com/v1beta/openai").rstrip('/')
    if base.endswith('/openai'):
        base = base[:-len('/openai')]
    return base.rstrip('/')


def _extract_json(text: str):
    raw = (text or '').strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.I)
    raw = re.sub(r'\s*```$', '', raw)
    try:
        return json.loads(raw)
    except Exception:
        m = re.search(r'\{.*\}', raw, flags=re.S)
        if m:
            return json.loads(m.group(0))
    raise ValueError('Gemini no devolvió un JSON válido para la ficha del archivo.')


def _prompt():
    return (
        "Analiza el archivo adjunto como documento administrativo. Devuelve SOLO un objeto JSON válido, sin markdown. "
        "Si no es una factura, recibo o documento con esos campos, deja los campos no aplicables como cadenas vacías. "
        "No inventes datos. Usa exactamente estas claves: "
        "document_type, category, summary, description, vendor, invoice_number, document_date, due_date, total_amount, "
        "currency, tax_amount, reference, tags. "
        "category debe ser una de: facturas, recibos, contratos, finanzas, documentos, personal, fotos, otros, sin_clasificar. "
        "total_amount y tax_amount deben ser cadenas conservando el importe tal como aparece. "
        "tags debe ser una lista corta de palabras. "
        "Para una foto de una factura, identifica proveedor, número, fecha, vencimiento, total, moneda e impuestos si son legibles."
    )


def _native_gemini(parts, model, key, base_url):
    url = f"{_gemini_root(base_url)}/models/{model}:generateContent"
    payload = {
        'contents': [{'parts': parts}],
        'generationConfig': {'temperature': 0.1, 'responseMimeType': 'application/json'}
    }
    r = requests.post(url, params={'key': key}, json=payload, timeout=180)
    if not r.ok:
        raise RuntimeError(f'Gemini HTTP {r.status_code}: {r.text[:900]}')
    data = r.json()
    text = ''
    for cand in data.get('candidates', []):
        for part in (cand.get('content') or {}).get('parts', []):
            if part.get('text'):
                text += part['text']
    if not text:
        raise RuntimeError('Gemini no devolvió contenido analizable.')
    return _extract_json(text)


def analyze_file(file_id: str):
    item = get_file(file_id)
    if not item:
        raise FileNotFoundError('Archivo no encontrado en la memoria de Zar.')
    path = files_dir() / item.get('category', 'sin_clasificar') / item.get('stored_name', '')
    if not path.exists():
        raise FileNotFoundError('El archivo no está disponible en el almacenamiento.')

    cfg = load()
    if cfg.get('provider') == 'local':
        raise RuntimeError('El análisis visual de archivos en V21 requiere un proveedor Gemini/API.')
    key = (cfg.get('api', {}).get('api_key') or '').strip()
    model = (cfg.get('api', {}).get('model') or 'gemini-3.6-flash').strip()
    base_url = cfg.get('api', {}).get('base_url') or 'https://generativelanguage.googleapis.com/v1beta/openai'
    if not key:
        raise RuntimeError('Falta la API key de Gemini para analizar archivos.')

    mime = item.get('mime') or mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    raw = path.read_bytes()
    if len(raw) > 50 * 1024 * 1024:
        raise RuntimeError('Este análisis admite archivos de hasta 50 MB.')

    parts = [
        {'text': _prompt()},
        {'inlineData': {'mimeType': mime, 'data': base64.b64encode(raw).decode('ascii')}}
    ]
    try:
        analysis = _native_gemini(parts, model, key, base_url)
    except RuntimeError as exc:
        detail = str(exc)
        if 'HTTP 429' not in detail and 'RESOURCE_EXHAUSTED' not in detail:
            raise
        fallback_model = (os.environ.get('ZAR_GEMINI_FALLBACK_MODEL') or 'gemini-3.5-flash-lite').strip()
        if not fallback_model or fallback_model == model:
            raise
        analysis = _native_gemini(parts, fallback_model, key, base_url)

    category = str(analysis.get('category') or item.get('category') or 'sin_clasificar').strip().lower()
    aliases = {'factura':'facturas','invoice':'facturas','recibo':'recibos','ticket':'recibos','contrato':'contratos','documento':'documentos','foto':'fotos'}
    category = aliases.get(category, category)
    note_bits = [x for x in [analysis.get('summary'), analysis.get('description'), analysis.get('vendor'), analysis.get('invoice_number'), analysis.get('document_date'), analysis.get('total_amount')] if x]
    note = ' · '.join(str(x) for x in note_bits)
    enriched = update_file(file_id, category=category, note=note)
    # Persist structured metadata directly in the index while retaining compatibility with previous schema.
    try:
        index_path = files_dir() / 'index.json'
        data = json.loads(index_path.read_text(encoding='utf-8')) if index_path.exists() else []
        for row in data:
            if row.get('id') == file_id:
                row['analysis'] = analysis
                row['updated_at'] = enriched.get('updated_at')
                break
        tmp = index_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(index_path)
        enriched = dict(enriched)
        enriched['analysis'] = analysis
    except Exception:
        pass
    return {'ok': True, 'file': public_item(enriched), 'analysis': analysis}
