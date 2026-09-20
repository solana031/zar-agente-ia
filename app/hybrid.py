import re
from datetime import datetime, timedelta

MONTHS = {
    "enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,
    "julio":7,"agosto":8,"septiembre":9,"setiembre":9,"octubre":10,
    "noviembre":11,"diciembre":12
}

def calendar_query_days(text):
    t = text.strip().lower()
    if not any(w in t for w in ("calendario", "calendar")):
        return None
    if not any(w in t for w in ("qué tengo", "que tengo", "qué hay", "que hay", "eventos", "citas")):
        return None
    if "pasado mañana" in t:
        return 2
    if "mañana" in t or "hoy" in t:
        return 1
    if any(w in t for w in ("próximos 7 días","proximos 7 dias","siguientes 7 días","siguientes 7 dias","esta semana")):
        return 7
    return 7

START_PATTERNS = [
    r"^\s*recuérdame\s+",
    r"^\s*recuérdame\s+que\s+",
    r"^\s*recordarme\s+",
    r"^\s*ponme\s+un\s+recordatorio\s+",
    r"^\s*pon\s+un\s+recordatorio\s+",
    r"^\s*añade\s+un\s+recordatorio\s+",
    r"^\s*añádeme\s+un\s+recordatorio\s+",
    r"^\s*crea\s+un\s+recordatorio\s+",
    r"^\s*créame\s+un\s+recordatorio\s+",
    r"^\s*crear\s+un\s+recordatorio\s+",
    r"^\s*ponme\s+un\s+aviso\s+",
    r"^\s*crea\s+un\s+aviso\s+",
]

def is_reminder_request(text):
    return any(re.search(p, text.strip().lower(), re.I) for p in START_PATTERNS)

def _extract_date(text, now):
    if "pasado mañana" in text:
        return (now + timedelta(days=2)).date()
    if "mañana" in text:
        return (now + timedelta(days=1)).date()
    if "hoy" in text:
        return now.date()
    m = re.search(r"\bel\s+(\d{1,2})(?:\s+de\s+([a-záéíóú]+))?", text)
    if not m:
        return None
    day = int(m.group(1))
    month = MONTHS.get(m.group(2), now.month) if m.group(2) else now.month
    try:
        candidate = datetime(now.year, month, day, tzinfo=now.tzinfo)
    except ValueError:
        return None
    if candidate.date() < now.date():
        candidate = candidate.replace(year=now.year + 1)
    return candidate.date()

def _extract_time(text):
    p = re.search(
        r"\ba\s+las?\s+(\d{1,2})(?::(\d{2}))?(?:\s*(?:h|horas?))?"
        r"(?:\s+de\s+la\s+(mañana|tarde|noche))?"
        r"(?:\s*(am|pm|a\.?\s*m\.?|p\.?\s*m\.?))?\b",
        text, re.I
    )
    if not p:
        return None
    hour, minute = int(p.group(1)), int(p.group(2) or 0)
    part = (p.group(3) or p.group(4) or "").lower().replace(".", "").replace(" ", "")
    if ("tarde" in part or "noche" in part or part == "pm") and hour < 12:
        hour += 12
    if ("mañana" in part or part == "am") and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return hour, minute

def parse_reminder(text, now=None):
    low = text.strip().lower()
    prefix_end = None
    for pat in START_PATTERNS:
        m = re.search(pat, low, re.I)
        if m:
            prefix_end = m.end()
            break
    if prefix_end is None:
        return None

    now = now or datetime.now().astimezone()
    day = _extract_date(low, now)
    tm = _extract_time(low)

    candidate = low[prefix_end:]
    candidate = re.sub(r"\bpasado mañana\b|\bmañana\b|\bhoy\b", " ", candidate)
    candidate = re.sub(r"\bel\s+\d{1,2}(?:\s+de\s+[a-záéíóú]+)?\b", " ", candidate)
    candidate = re.sub(
        r"\ba\s+las?\s+\d{1,2}(?::\d{2})?(?:\s*(?:h|horas?))?"
        r"(?:\s+de\s+la\s+(?:mañana|tarde|noche))?"
        r"(?:\s*(?:am|pm|a\.?\s*m\.?|p\.?\s*m\.?))?\b",
        " ", candidate, flags=re.I
    )
    candidate = re.sub(r"\b(?:en mi calendario|en el calendario|en calendar)\b", " ", candidate)
    candidate = re.sub(r"^\s*(?:que se llame|llamado|titulad[oa])\s+", "", candidate)
    candidate = re.sub(r"\s+", " ", candidate).strip(" .,:;\"“”'")

    # If the user explicitly asked for a reminder but omitted one of its key fields,
    # return a structured clarification instead of routing to the external AI.
    missing = []
    if day is None:
        missing.append("fecha")
    if tm is None:
        missing.append("hora")
    if not candidate:
        missing.append("título")

    if missing:
        return {"needs_clarification": missing, "summary": candidate or None, "day": day, "time": tm}

    hour, minute = tm
    start = datetime(day.year, day.month, day.day, hour, minute, tzinfo=now.tzinfo)
    end = start + timedelta(minutes=30)
    return {
        "needs_clarification": [],
        "summary": candidate[:120].capitalize(),
        "start_iso": start.isoformat(),
        "end_iso": end.isoformat(),
        "date_human": start.strftime("%d/%m/%Y"),
        "time_human": start.strftime("%H:%M")
    }


def media_intent(text):
    """Detecta órdenes claras para abrir búsquedas de YouTube o Spotify."""
    t = text.strip()
    low = t.lower()
    platform = None
    if 'youtube' in low or 'youtube music' in low:
        platform = 'youtube'
    elif 'spotify' in low:
        platform = 'spotify'
    if not platform:
        return None
    # Evita capturar frases puramente informativas sobre la plataforma.
    if not any(w in low for w in ('busca', 'buscar', 'abre', 'abrir', 'pon', 'reproduce', 'reproducir', 'escucha', 'mira', 'youtube', 'spotify')):
        return None
    q = low
    q = re.sub(r'\b(en\s+)?(youtube|youtube music|spotify)\b', ' ', q, flags=re.I)
    q = re.sub(r'\b(?:busca|buscar|abre|abrir|pon|reproduce|reproducir|escucha|mira)\b', ' ', q, flags=re.I)
    q = re.sub(r'\b(?:un|una|el|la|los|las)\s+(?:vídeo|video|canción|cancion|tema|playlist|música|musica)\b', ' ', q, flags=re.I)
    q = re.sub(r'\s+', ' ', q).strip(" .,:;¿?¡!\"“”'")
    if not q:
        return {"platform": platform, "query": ""}
    return {"platform": platform, "query": q[:300]}

def gmail_intent(text):
    t = text.strip().lower()
    if not any(w in t for w in ("gmail", "correo", "correos", "email", "emails")):
        return None

    if any(w in t for w in ("sin leer", "no leídos", "no leidos", "no leídas", "no leidas", "no leído", "no leido")):
        return {"type":"search","query":"in:inbox is:unread","max_results":10}
    if any(w in t for w in ("últimos", "ultimos", "recientes", "últimos correos", "ultimos correos")):
        return {"type":"search","query":"in:inbox","max_results":10}
    m = re.search(r"(?:de|from)\s+([^\s,]+@[^\s,]+)", t)
    if m:
        return {"type":"search","query":f"from:{m.group(1)}","max_results":10}
    if "hoy" in t:
        return {"type":"search","query":"newer_than:1d","max_results":10}
    if any(w in t for w in ("comprueba", "comprueba que tienes acceso", "tienes acceso")):
        return {"type":"status"}
    return {"type":"search","query":"in:inbox","max_results":10}

def _has_gmail_reference(t):
    return any(r in t for r in (
        "último correo", "ultimo correo", "este correo", "ese correo",
        "último mensaje", "ultimo mensaje", "este mensaje", "ese mensaje",
        "correo que acabas de abrir", "correo que abriste", "mensaje que acabas de abrir",
        "ese email", "este email", "último email", "ultimo email"
    ))


def _multi_action_gmail_request(t):
    """True when the user asks for more than one conversational Gmail action at once."""
    action_groups = [
        ("open", ("abre", "abrir", "lee", "leer", "mira", "revisa", "revisar", "enséñame", "ensename")),
        ("understand", ("resume", "resumelo", "resúmelo", "resúmeme", "resumeme", "qué quiere", "que quiere", "qué me pide", "que me pide", "qué dice", "que dice", "de qué va", "de que va", "explícame", "explicame")),
        ("reply", ("redacta", "redáctame", "redactame", "responde", "respóndele", "respondele", "contesta", "contéstale", "contestale", "escribe una respuesta", "prepara una respuesta", "respóndele", "responde a"))
    ]
    hits = 0
    for _, words in action_groups:
        if any(w in t for w in words):
            hits += 1
    return hits >= 2 and ("correo" in t or "email" in t or "mensaje" in t or _has_gmail_reference(t))



def gmail_compound_intent(text):
    """Detecta una petición Gmail compuesta de leer/comprender + responder.

    Devuelve la instrucción concreta para la respuesta, o None si no encaja.
    Se resuelve de forma determinista para que las órdenes naturales no dependan
    de que el modelo decida correctamente cuándo llamar una herramienta.
    """
    t = re.sub(r"\s+", " ", text.strip().lower())
    if not _has_gmail_reference(t) and "gmail" not in t and "correo" not in t and "email" not in t and "mensaje" not in t:
        return None

    open_words = ("abre", "abrir", "lee", "leer", "mira", "revisa", "revisar", "enséñame", "ensename", "muéstrame", "muestrame")
    understand_words = ("dime qué quiere", "dime que quiere", "qué quiere", "que quiere", "qué me pide", "que me pide", "qué dice", "que dice", "de qué va", "de que va", "resúmelo", "resumelo", "hazme un resumen", "haz un resumen")
    reply_pattern = re.compile(
        r"(?:y\s+)?(?:respóndele|respondele|contéstale|contestale|respóndelo|respondelo|responde|contesta|dile|escribe(?:le)?|prepara(?:le)?\s+una\s+respuesta|redacta(?:le)?(?:\s+una\s+respuesta)?)\s*(?:que\s+)?(.+)$",
        re.I
    )

    has_open = any(v in t for v in open_words) and _has_gmail_reference(t)
    has_understand = any(v in t for v in understand_words)
    m = reply_pattern.search(t)
    if not ((has_open or _has_gmail_reference(t)) and has_understand and m):
        return None

    instruction = m.group(1).strip(" .,:;\"“”'")
    if not instruction:
        return None
    return {"type": "latest_understand_reply", "instruction": instruction}

def gmail_is_complex_request(text):
    """Indica que una petición de Gmail contiene varias acciones.

    Las peticiones de correo compuestas se resuelven en la capa de aplicación
    para mantener un comportamiento predecible incluso con modelos locales.
    """
    t = text.strip().lower()
    return bool(gmail_compound_intent(t) or _multi_action_gmail_request(t))


def gmail_direct_intent(text):
    t = text.strip().lower()

    # Las peticiones compuestas deben llegar al agente local para que pueda
    # encadenar herramientas y entender la intención completa del usuario.
    if _multi_action_gmail_request(t):
        return None

    # Abrir/leer el último correo: aceptamos lenguaje cotidiano, no solo una
    # frase exacta del tipo «abre mi último correo».
    latest_verbs = ("abre", "abrir", "lee", "leer", "mira", "revisa", "revisar", "enséñame", "ensename", "muéstrame", "muestrame")
    latest_refs = ("mi último correo", "mi ultimo correo", "el último correo", "el ultimo correo", "mi último email", "mi ultimo email", "mi último mensaje", "mi ultimo mensaje")
    if any(v in t for v in latest_verbs) and any(r in t for r in latest_refs):
        return {"type":"latest"}

    if any(q in t for q in (
        "qué dice mi último correo", "que dice mi ultimo correo",
        "qué pone mi último correo", "que pone mi ultimo correo",
        "de qué va mi último correo", "de que va mi ultimo correo"
    )):
        return {"type":"latest"}

    # Resumen y comprensión de contexto: estas órdenes cortas no deben volver a
    # disparar una búsqueda genérica de Gmail.
    summary_phrases = (
        "resúmelo", "resumelo", "resume ese correo", "resumeme ese correo",
        "resúmeme ese correo", "resume este correo", "resúmeme este correo",
        "resume el último correo", "resume el ultimo correo",
        "resumeme el último correo", "resúmeme el último correo",
        "resume el correo que abriste", "resume el correo que abrí",
        "resume el ultimo correo que te he pedido que abras",
        "resume el último correo que te he pedido que abras",
        "hazme un resumen", "haz un resumen", "dime qué quiere", "dime que quiere",
        "qué me pide este correo", "que me pide este correo",
        "qué me está pidiendo", "que me esta pidiendo",
        "explícame este correo", "explicame este correo"
    )
    if any(w in t for w in summary_phrases):
        return {"type":"summarize_context"}

    # Redacción/respuesta contextual: si es una orden simple sobre el correo
    # actual, la resolvemos aquí; las órdenes compuestas pasan al agente local.
    draft_words = (
        "redacta", "redactame", "redáctame", "responde", "respóndele",
        "respondele", "contesta", "contéstale", "contestale",
        "escribe una respuesta", "prepara una respuesta", "responder a"
    )
    references = (
        "último correo", "ultimo correo", "ese correo", "este correo",
        "último mensaje", "ultimo mensaje", "correo que acabas de abrir",
        "correo que abriste", "ese email", "este email"
    )
    if any(w in t for w in draft_words) and any(r in t for r in references):
        return {"type":"draft_context"}

    if not any(w in t for w in ("gmail", "correo", "correos", "email", "emails", "mensaje")):
        return None

    m = re.search(r"(?:abre|lee|abrir|leer|mira|revisa|revisar)\s+(?:el\s+)?correo\s+de\s+([^\s,]+@[^\s,]+)", t)
    if m:
        return {"type":"from", "query":f"from:{m.group(1)}", "max_results":5}

    return None


# ---------------- Google Contacts routing ----------------

def contacts_intent(text):
    t = re.sub(r"\s+", " ", (text or "").strip())
    low = t.lower()
    if not low: return None
    if not re.search(r"\bcontactos?\b|\bagenda\b|\bpersona\b", low):
        # Natural name-based email requests still need contact lookup.
        if not re.search(r"\b(?:escribe|escríbele|escribile|envía|enviale|mándale|mandale|llama|llámale|busca)\b", low):
            return None
    if any(v in low for v in ("mis contactos", "lista mis contactos", "listar contactos", "enséñame mis contactos", "ensename mis contactos")):
        return {"type":"contacts_list", "limit":20}
    m = re.search(r"(?:busca|buscar|encuentra|encontrar|localiza|localizar)\s+(?:el\s+)?(?:contacto\s+de\s+)?(.+)$", t, re.I)
    if m and not any(x in low for x in ("google drive", "restaurante", "gasolinera")):
        q=m.group(1).strip(" .,:;\"“”'")
        if q and len(q) < 100:
            return {"type":"contacts_search", "query":q, "limit":10}
    m = re.search(r"(?:escríbele|escribile|escribe a|envíale un correo a|enviale un correo a|mándale un correo a|mandale un correo a|envía un correo a|envia un correo a)\s+([^,]+?)(?:\s+que\s+(.+))?$", t, re.I)
    if m:
        return {"type":"email_to_contact", "name":m.group(1).strip(), "instruction":(m.group(2) or "").strip()}
    # Mutaciones de agenda: se detectan antes del modelo para impedir que una
    # orden explícita de contacto pueda terminar en Forms, Sheets o Gmail.
    if re.search(r'\b(?:crear|crea|añade|anade|guardar|guarda|nuevo|nueva)\b', low) and re.search(r'\bcontacto\b', low):
        m = re.search(r'(?:contacto\s+(?:de|llamado|llamada|que se llama|que se llame)|contacto)\s+(.+)$', t, re.I)
        if m:
            raw = m.group(1).strip(' .,:;"“”\'')
            em = re.search(r'([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})', raw, re.I)
            ph = re.search(r'(?:tel(?:éfono|efono)?|móvil|movil|phone)\s*[:=]?\s*([+\d][\d .()-]{6,})', raw, re.I)
            raw_name = re.sub(r'^como\s+', '', raw, flags=re.I)
            raw_name = re.sub(r'\s+(?:con\s+)?(?:email|correo|tel(?:éfono|efono)?|móvil|movil|phone)\s*[:=]?.*$', '', raw_name, flags=re.I).strip(' ,;')
            return {"type":"contacts_create", "name":raw_name or raw, "email":em.group(1) if em else '', "phone":ph.group(1).strip() if ph else ''}
    if re.search(r'\b(?:actualiza|actualizar|modifica|modificar|cambia|cambiar|edita|editar)\b', low) and re.search(r'\bcontacto\b', low):
        m = re.search(r'contacto\s+(?:de\s+)?(.+)$', t, re.I)
        if m:
            return {"type":"contacts_update", "name":m.group(1).strip(' .,:;"“”\'')}
    return None


# ---------------- Google Workspace routing ----------------

def workspace_intent(text):
    """Detecta órdenes comunes de Workspace y devuelve una intención estructurada."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    low = t.lower()
    if not low:
        return None

    # Drive lectura/búsqueda
    if re.search(r"\bgoogle drive\b|\bdrive\b", low):
        if any(v in low for v in ("busca", "buscar", "encuentra", "encontrar", "localiza", "localizar")):
            m = re.search(r"(?:archivo|documento|carpeta)\s+(?:llamado|llamada|titulado|titulada|que se llama|que se llame|de nombre)\s+[\"“']?(.+?)[\"”']?$", t, re.I)
            if m:
                return {"type":"drive_search", "name":m.group(1).strip(" .,:;\"“”'"), "max_results":20}
            return {"type":"drive_list", "max_results":20}
        if any(v in low for v in ("lista", "listar", "enséñame", "ensename", "muéstrame", "muestrame")) and any(v in low for v in ("archivos", "documentos")):
            return {"type":"drive_list", "max_results":20}

    # Docs: extraemos título tras "llamado/titulado/que se llame" y texto tras "escribe dentro"
    if re.search(r"\bgoogle docs\b|\bdocumento de google\b|\bgoogle doc\b", low):
        if any(v in low for v in ("crea", "crear", "haz", "hacer")):
            mt = re.search(r"(?:llamado|llamada|titulado|titulada|que se llama|que se llame)\s+[\"“']?(.+?)(?:[\"”']?\s+y\s+escribe(?:\s+dentro)?\s*[:\-]?\s*(.+))?$", t, re.I)
            if mt:
                title = mt.group(1).strip(" .,:;\"“”'")
                text0 = (mt.group(2) or "").strip(" .,:;\"“”'")
                return {"type":"docs_create", "title":title, "text":text0}
            return None

    # Sheets: título tras "llamada/llamado/titulada/titulado/que se llame"
    if re.search(r"\bgoogle sheets\b|\bsheets\b|\bhoja de cálculo\b|\bhoja de calculo\b|\bexcel\b|\barchivo excel\b", low):
        if any(v in low for v in ("crea", "crear", "haz", "hacer")):
            mt = re.search(r"(?:llamada|llamado|titulada|titulado|que se llama|que se llame)\s+[\"“']?(.+?)[\"”']?$", t, re.I)
            if mt:
                return {"type":"sheets_create", "title":mt.group(1).strip(" .,:;\"“”'")}
            # "Crea una hoja de cálculo llamada X" siempre debería caer aquí.
            mt = re.search(r"(?:hoja de cálculo|hoja de calculo|hoja|sheet|sheets)\s+(?:llamada|llamado|titulada|titulado|que se llame)\s+[\"“']?(.+?)[\"”']?$", t, re.I)
            if mt:
                return {"type":"sheets_create", "title":mt.group(1).strip(" .,:;\"“”'")}

    # Slides
    if re.search(r"\bgoogle slides\b|\bslides\b|\bpresentación\b|\bpresentacion\b", low):
        if any(v in low for v in ("crea", "crear", "haz", "hacer")):
            mt = re.search(r"(?:llamada|llamado|titulada|titulado|que se llama|que se llame)\s+[\"“']?(.+?)[\"”']?$", t, re.I)
            if mt:
                return {"type":"slides_create", "title":mt.group(1).strip(" .,:;\"“”'")}

    # Forms: si el usuario dice explícitamente "formulario/forms", Forms tiene
    # prioridad absoluta sobre Gmail. La petición puede contener "correo",
    # "email", "enviar", etc. y seguirá siendo una orden de Forms.
    forms_explicit = re.search(r"\bgoogle\s+forms\b|\bforms\b|\bformulario\b|\bformularios\b", low)
    forms_natural = re.search(r"\bencuesta\b|\bcuestionario\b", low) and any(v in low for v in ("crea", "crear", "créame", "creame", "haz", "hazme", "hacer", "prepara", "prepárame", "preparame", "necesito", "quiero"))
    if forms_explicit or forms_natural:
        if any(v in low for v in (
            "crea", "crear", "créame", "creame", "haz", "hazme", "hacer",
            "prepara", "prepárame", "preparame", "preparar", "necesito",
            "quiero", "quiero que hagas", "dame"
        )):
            title = "Formulario de Google"
            description = ""

            # 1) Si el usuario da un título explícito, ese es el título real.
            # Primero soportamos títulos entre comillas; después, títulos normales
            # seguidos de "para ..." o "con descripción ...".
            mt = re.search(
                r"(?:llamado|llamada|titulado|titulada|que se llama|que se llame)\s+[\"“']([^\"”']+)[\"”']",
                t, re.I
            )
            if mt:
                title = mt.group(1).strip(" .,:;") or title
                rest = t[mt.end():].strip(" .,:;")
                dm = re.search(r"(?:para|con\s+(?:descripci[oó]n|descripcion))\s+(.+)$", rest, re.I)
                if dm:
                    description = dm.group(1).strip(" .,:;\"“”'")
            else:
                mt = re.search(
                    r"(?:llamado|llamada|titulado|titulada|que se llama|que se llame)\s+(.+?)(?:\s+para\s+(.+)|\s+con\s+(?:descripci[oó]n|descripcion)\s+(.+))?$",
                    t, re.I
                )
                if mt:
                    title = mt.group(1).strip(" .,:;\"“”'") or title
                    description = (mt.group(2) or mt.group(3) or "").strip(" .,:;\"“”'")
                else:
                    # 2) "formulario de satisfacción" / "formulario sobre clientes"
                    #    => usamos ese tema como título.
                    mt = re.search(
                        r"(?:google\s+forms|formulario|formularios|forms)\s+(?:de|sobre)\s+(.+)$",
                        t, re.I
                    )
                    if mt:
                        raw = mt.group(1).strip(" .,:;\"“”'")
                        # Si después del tema hay un "para ...", lo tratamos como
                        # descripción en lugar de meterlo entero en el título.
                        dm = re.search(r"\s+para\s+(.+)$", raw, re.I)
                        if dm:
                            title = raw[:dm.start()].strip(" .,:;\"“”'") or title
                            description = dm.group(1).strip(" .,:;\"“”'")
                        else:
                            title = raw or title
                    else:
                        # 3) "créame un formulario para recopilar emails" o
                        #    "necesito un formulario para clientes". No confundimos
                        #    el propósito con el nombre del formulario.
                        mt = re.search(
                            r"(?:google\s+forms|formulario|formularios|forms)\s+para\s+(.+)$",
                            t, re.I
                        )
                        if mt:
                            description = mt.group(1).strip(" .,:;\"“”'")

            if not forms_explicit and forms_natural and title == "Formulario de Google":
                mt = re.search(r"(?:encuesta|cuestionario)\s+(?:de|sobre)\s+(.+)$", t, re.I)
                if mt:
                    title = ("Encuesta " + mt.group(1).strip(" .,:;\"“”'"))[:120]
                else:
                    description = t.strip(" .,:;\"“”'")
            return {"type":"forms_create", "title":title, "description":description}

    return None
