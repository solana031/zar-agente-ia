import base64
import json
import mimetypes
import os
import re
from pathlib import Path
import requests
import time

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
        "Analiza exhaustivamente el archivo adjunto como documento, imagen o comprobante. "
        "Devuelve SOLO un objeto JSON válido, sin markdown. No inventes datos y marca como no legible "
        "lo que no pueda determinarse. Identifica el tipo de documento, idioma y propósito. Extrae todos "
        "los datos visibles relevantes, no solo los de una factura. Usa exactamente estas claves: "
        "document_type, document_subtype, language, summary, description, issuer, recipient, vendor, "
        "invoice_number, reference, document_date, due_date, dates, addresses, emails, phones, "
        "identifiers, currency, total_amount, subtotal, tax_amount, taxes, discounts, amounts, "
        "line_items, people, entities, tables, tags, full_text, visual_observations. "
        "dates debe ser una lista de fechas detectadas; amounts una lista de importes con su etiqueta y moneda "
        "si aparece; line_items una lista de conceptos/cantidades/precios/impuestos; taxes una lista con tipo, "
        "porcentaje y cantidad; people y entities deben conservar nombres y roles; tables debe representar "
        "las tablas legibles; identifiers debe recoger DNI/NIE/NIF/CIF, números de factura, cuentas, referencias "
        "u otros identificadores visibles, sin inventar ni ocultar datos. full_text debe contener una "
        "transcripción fiel de todo el texto legible, respetando el orden aproximado. "
        "Si es una foto, captura o documento escaneado, aplica OCR visual. Si es un PDF, analiza todas las "
        "páginas que puedas. Para facturas, reconoce proveedor, receptor, número, fecha, vencimiento, divisa, "
        "subtotal, IVA/impuestos, descuentos, total y líneas. Para nóminas, reconoce empresa, trabajador, "
        "periodo, conceptos, devengos, deducciones, bases, impuestos y líquido. Para cualquier otro documento, "
        "extrae los campos específicos que sean visibles dentro de las claves genéricas. "
        "category debe ser una de: facturas, recibos, contratos, finanzas, documentos, personal, fotos, otros, sin_clasificar. "
        "tags debe ser una lista corta de palabras. "
        "Añade además business_records con exactamente dos listas: closures y shifts. "
        "Si el documento es un cierre de caja/TPV, closures debe contener objetos con: date, time, cash, card, closing_total, tpv_total, operations, tips, discrepancy, notes. "
        "Si el documento contiene turnos/horarios, shifts debe contener objetos con: employee, date, start_time, end_time, hours, paid_hours, pending_hours, notes. "
        "Usa null cuando un campo no sea legible y no inventes valores. Si no aplica, usa listas vacías."
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
    models = [model]
    fallback_model = (os.environ.get('ZAR_GEMINI_FALLBACK_MODEL') or 'gemini-3.5-flash-lite').strip()
    if fallback_model and fallback_model not in models:
        models.append(fallback_model)
    last_exc = None
    analysis = None
    for model_name in models:
        for attempt in range(3):
            try:
                analysis = _native_gemini(parts, model_name, key, base_url)
                break
            except RuntimeError as exc:
                last_exc = exc
                detail = str(exc)
                transient = any(x in detail for x in ('HTTP 429','HTTP 500','HTTP 502','HTTP 503','HTTP 504','RESOURCE_EXHAUSTED','UNAVAILABLE'))
                if not transient:
                    raise
                if attempt < 2:
                    time.sleep(1.5 * (2 ** attempt))
        if analysis is not None:
            break
    if analysis is None:
        # Persist a retryable analysis state instead of losing the saved file.
        try:
            index_path = files_dir() / 'index.json'
            data = json.loads(index_path.read_text(encoding='utf-8')) if index_path.exists() else []
            for row in data:
                if row.get('id') == file_id:
                    row['analysis_status'] = 'pending_retry'
                    row['analysis_error'] = str(last_exc or 'Proveedor visual no disponible temporalmente')[:1200]
                    break
            tmp = index_path.with_suffix('.tmp')
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            tmp.replace(index_path)
        except Exception:
            pass
        raise RuntimeError('El archivo se ha guardado, pero el análisis visual está temporalmente saturado. ZAR lo ha dejado pendiente de reintento; puedes volver a pulsar Analizar más tarde.')

    # Mantener la ficha rica pero acotada para que el índice persistente no crezca sin control.
    if isinstance(analysis.get('full_text'), str):
        analysis['full_text'] = analysis['full_text'][:30000]
    for key, limit in [('description',6000),('summary',3000),('visual_observations',5000)]:
        if isinstance(analysis.get(key), str):
            analysis[key] = analysis[key][:limit]
    for key in ('dates','addresses','emails','phones','identifiers','amounts','line_items','people','entities','tables','taxes','tags'):
        if not isinstance(analysis.get(key), list):
            analysis[key] = []
    if not isinstance(analysis.get('business_records'), dict):
        analysis['business_records']={'closures':[],'shifts':[]}
    for key in ('closures','shifts'):
        if not isinstance(analysis['business_records'].get(key), list):
            analysis['business_records'][key]=[]

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
