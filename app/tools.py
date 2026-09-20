from datetime import datetime
import webbrowser
from urllib.parse import quote
try:
    from .memory import remember
    from .google_calendar import upcoming_events, calendar_status, create_event
    from .gmail import recent_messages, search_messages, gmail_status, get_message, get_latest, send_message, create_draft, update_draft
except ImportError:
    from .memory import remember
    from .google_calendar import upcoming_events, calendar_status, create_event
    from .gmail import recent_messages, search_messages, gmail_status, get_message, get_latest, send_message, create_draft, update_draft

_CURRENT_USER_MESSAGE = ""

def set_current_user_message(message):
    global _CURRENT_USER_MESSAGE
    _CURRENT_USER_MESSAGE = message or ""

def _current_user_message():
    return _CURRENT_USER_MESSAGE

TOOL_DEFINITIONS = [
    {"type":"function","name":"zar_get_context","description":"Devuelve el estado actual de Zar: correo activo, resumen, borrador actual, ID del borrador, calendario pendiente y foco. Úsalo antes de actuar cuando el usuario emplee referencias como «ese», «eso», «lo de antes», «la reunión», «el borrador» o «haz lo mismo». Así puedes resolver la referencia contra el estado real de la conversación.","parameters":{"type":"object","properties":{},"additionalProperties":False},"strict":True},
    {"type":"function","name":"zar_set_task_state","description":"Actualiza el estado persistente de la tarea actual. Úsalo cuando el usuario cambie de objeto o de fase (por ejemplo correo activo, borrador, evento, tarea pendiente).","parameters":{"type":"object","properties":{"intent":{"type":"string"},"object_type":{"type":"string"},"object_id":{"type":"string"},"action":{"type":"string"},"risk":{"type":"string","enum":["low","medium","high","irreversible"]},"status":{"type":"string"},"summary":{"type":"string"}},"required":["intent","object_type","action","risk","status","summary"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"save_memory","description":"Guarda un dato o preferencia de forma local.","parameters":{"type":"object","properties":{"text":{"type":"string"}},"required":["text"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"zar_memory_search","description":"Busca en la memoria local persistente de Zar: conversaciones antiguas, recuerdos, contenido de archivos subidos y metadatos de proyectos/archivos generados. No requiere Google. Úsala cuando el usuario pregunte por algo pasado o por lo aprendido de un documento.","parameters":{"type":"object","properties":{"query":{"type":"string"},"limit":{"type":"integer","minimum":1,"maximum":20}},"required":["query"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"get_local_time","description":"Devuelve la fecha y hora local del ordenador.","parameters":{"type":"object","properties":{},"additionalProperties":False},"strict":True},
    {"type":"function","name":"open_url","description":"Abre una URL http o https en el navegador.","parameters":{"type":"object","properties":{"url":{"type":"string"}},"required":["url"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"search_youtube","description":"Abre una búsqueda de YouTube.","parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"search_spotify","description":"Abre una búsqueda de Spotify.","parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"],"additionalProperties":False},"strict":True},



    {"type":"function","name":"video_get_current_project","description":"Devuelve el proyecto de vídeo activo de Zar y su timeline. Úsalo antes de editar cuando el usuario diga «este vídeo», «el vídeo que estamos haciendo» o «lo de antes».","parameters":{"type":"object","properties":{},"additionalProperties":False},"strict":True},
    {"type":"function","name":"video_edit_project","description":"Edita de forma no destructiva el proyecto de vídeo activo a partir de una orden natural. Puede reordenar/quitar clips, recortar, cambiar velocidad, zoom, giro, volteo, look, texto, transiciones y optimizar un montaje para vídeo corto. El archivo original se conserva hasta que se exporta un nuevo render.","parameters":{"type":"object","properties":{"project_id":{"type":"string"},"instruction":{"type":"string"}},"required":["instruction"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"video_viral_optimize","description":"Aplica una optimización heurística al proyecto para Shorts/TikTok/YouTube basada en señales públicas de creatividad de plataforma: apertura rápida, ritmo, movimiento, formato y transiciones. No garantiza viralidad.","parameters":{"type":"object","properties":{"project_id":{"type":"string"},"platform":{"type":"string","enum":["shorts","tiktok","youtube"]}},"required":["platform"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"video_transition_catalog","description":"Devuelve la biblioteca de transiciones disponibles en el editor de Zar agrupadas por estilo.","parameters":{"type":"object","properties":{},"additionalProperties":False},"strict":True},

    {"type":"function","name":"file_list","description":"Lista archivos guardados en la memoria de Zar. Puedes filtrar por categoría.","parameters":{"type":"object","properties":{"category":{"type":"string"}},"additionalProperties":False},"strict":True},
    {"type":"function","name":"file_search","description":"Busca archivos guardados por nombre, categoría o nota. Devuelve resultados con enlace de descarga.","parameters":{"type":"object","properties":{"query":{"type":"string"},"category":{"type":"string"},"limit":{"type":"integer","minimum":1,"maximum":50}},"required":["query"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"file_get","description":"Obtiene un archivo guardado concreto y su enlace de descarga.","parameters":{"type":"object","properties":{"file_id":{"type":"string"}},"required":["file_id"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"file_update_metadata","description":"Clasifica u organiza un archivo guardado y puede añadir una nota descriptiva. No borra el archivo.","parameters":{"type":"object","properties":{"file_id":{"type":"string"},"category":{"type":"string"},"note":{"type":"string"}},"required":["file_id"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"file_analyze","description":"Analiza visualmente un archivo guardado, especialmente facturas, recibos y documentos. Usa Gemini/API, extrae campos legibles, clasifica el archivo y guarda la ficha en la memoria de Zar. No modifica ni elimina el archivo original.","parameters":{"type":"object","properties":{"file_id":{"type":"string"}},"required":["file_id"],"additionalProperties":False},"strict":True},


    {"type":"function","name":"gmail_get_latest","description":"Obtiene el último correo de la bandeja de entrada con su contenido de texto para poder leerlo y resumirlo.","parameters":{"type":"object","properties":{},"additionalProperties":False},"strict":True},

    {"type":"function","name":"gmail_get_current_context","description":"Devuelve el correo actualmente activo, el borrador pendiente y el ID del borrador guardado en la conversación de Zar. Úsalo para entender frases como «ese correo», «lo de antes», «la respuesta que preparaste» o «¿qué borrador tienes?».","parameters":{"type":"object","properties":{},"additionalProperties":False},"strict":True},
    {"type":"function","name":"gmail_save_current_draft","description":"Guarda o actualiza en Gmail el borrador actualmente preparado por Zar. NO lo envía. Úsalo ante cualquier petición del usuario equivalente a guardar, conservar, dejar listo o almacenar el borrador actual.","parameters":{"type":"object","properties":{},"additionalProperties":False},"strict":True},
    {"type":"function","name":"gmail_prepare_email","description":"Prepara un correo para revisión del usuario. NO lo envía. Debe usarse cuando el usuario quiera redactar, contestar o escribir un correo.","parameters":{"type":"object","properties":{"to":{"type":"string"},"subject":{"type":"string"},"body":{"type":"string"},"reply_to_message_id":{"type":"string"}},"required":["to","subject","body"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"calendar_status","description":"Comprueba el acceso al calendario principal de Google.","parameters":{"type":"object","properties":{},"additionalProperties":False},"strict":True},
    {"type":"function","name":"calendar_upcoming","description":"Consulta próximos eventos del calendario principal de Google.","parameters":{"type":"object","properties":{"days":{"type":"integer","minimum":1,"maximum":31},"max_results":{"type":"integer","minimum":1,"maximum":20}},"required":["days","max_results"],"additionalProperties":False},"strict":True},

    {"type":"function","name":"gmail_status","description":"Comprueba el acceso de Zar a Gmail y devuelve la cuenta conectada.","parameters":{"type":"object","properties":{},"additionalProperties":False},"strict":True},
    {"type":"function","name":"gmail_recent","description":"Consulta los mensajes recientes de Gmail según una consulta de Gmail.","parameters":{"type":"object","properties":{"query":{"type":"string"},"max_results":{"type":"integer","minimum":1,"maximum":20}},"required":["query","max_results"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"gmail_search","description":"Busca mensajes de Gmail usando el formato de búsqueda de Gmail. Ejemplos: from:persona@example.com, is:unread, newer_than:7d.","parameters":{"type":"object","properties":{"query":{"type":"string"},"max_results":{"type":"integer","minimum":1,"maximum":20}},"required":["query","max_results"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"gmail_get_message","description":"Obtiene el contenido de un mensaje concreto de Gmail para poder leerlo, entenderlo o responderlo.","parameters":{"type":"object","properties":{"message_id":{"type":"string"}},"required":["message_id"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"contacts_status","description":"Comprueba el acceso de Zar a Google Contacts.","parameters":{"type":"object","properties":{}},"strict":True},
    {"type":"function","name":"contacts_search","description":"Busca contactos de Google Contacts por nombre, correo, teléfono o empresa. Úsalo para resolver destinatarios por nombre en órdenes como «escríbele a Juan».","parameters":{"type":"object","properties":{"query":{"type":"string"},"limit":{"type":"integer","minimum":1,"maximum":20}},"required":["query"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"contacts_get","description":"Obtiene los datos completos de un contacto de Google Contacts a partir de su resourceName.","parameters":{"type":"object","properties":{"resource_name":{"type":"string"}},"required":["resource_name"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"contacts_create","description":"Crea un contacto nuevo en Google Contacts. Es una modificación externa y requiere confirmación de Zar antes de ejecutarse.","parameters":{"type":"object","properties":{"name":{"type":"string"},"email":{"type":"string"},"phone":{"type":"string"},"company":{"type":"string"}},"required":["name"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"contacts_update","description":"Actualiza un contacto existente en Google Contacts. Es una modificación externa y requiere confirmación de Zar antes de ejecutarse.","parameters":{"type":"object","properties":{"resource_name":{"type":"string"},"etag":{"type":"string"},"name":{"type":"string"},"email":{"type":"string"},"phone":{"type":"string"},"company":{"type":"string"}},"required":["resource_name","etag"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"google_workspace_status","description":"Comprueba si Zar tiene acceso a Google Workspace (Drive, Docs, Sheets, Slides y Forms).","parameters":{"type":"object","properties":{}},"strict":True},
    {"type":"function","name":"drive_search","description":"Busca en Google Drive archivos por nombre. Usa solo archivos accesibles mediante la autorización actual.","parameters":{"type":"object","properties":{"name":{"type":"string"},"max_results":{"type":"integer","minimum":1,"maximum":20}},"required":["name"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"drive_list_recent","description":"Lista archivos recientes de Google Drive accesibles para Zar.","parameters":{"type":"object","properties":{"max_results":{"type":"integer","minimum":1,"maximum":20}},"additionalProperties":False},"strict":True},
    {"type":"function","name":"docs_create","description":"Crea un documento de Google Docs con un título y, opcionalmente, texto inicial. Es una modificación externa y la aplicación debe exigir confirmación antes de ejecutar una acción de este tipo.","parameters":{"type":"object","properties":{"title":{"type":"string"},"text":{"type":"string"}},"required":["title"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"docs_append","description":"Añade texto al final de un documento de Google Docs existente. Acción de modificación externa: requiere confirmación de la aplicación.","parameters":{"type":"object","properties":{"document_id":{"type":"string"},"text":{"type":"string"}},"required":["document_id","text"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"sheets_create","description":"Crea una hoja de cálculo de Google Sheets con el título indicado. Acción externa: requiere confirmación de la aplicación.","parameters":{"type":"object","properties":{"title":{"type":"string"}},"required":["title"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"sheets_read","description":"Lee un rango de una hoja de cálculo de Google Sheets.","parameters":{"type":"object","properties":{"spreadsheet_id":{"type":"string"},"range_a1":{"type":"string"}},"required":["spreadsheet_id","range_a1"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"sheets_write","description":"Escribe valores en un rango de Google Sheets. Acción externa: requiere confirmación de la aplicación.","parameters":{"type":"object","properties":{"spreadsheet_id":{"type":"string"},"range_a1":{"type":"string"},"values":{"type":"array","items":{"type":"array","items":{}}}},"required":["spreadsheet_id","range_a1","values"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"slides_create","description":"Crea una presentación de Google Slides con el título indicado. Acción externa: requiere confirmación de la aplicación.","parameters":{"type":"object","properties":{"title":{"type":"string"}},"required":["title"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"forms_create","description":"Crea un formulario de Google Forms con el título indicado. Acción externa: requiere confirmación de la aplicación.","parameters":{"type":"object","properties":{"title":{"type":"string"},"description":{"type":"string"}},"required":["title"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"forms_add_question","description":"Añade una pregunta de texto a un formulario de Google Forms existente. Acción externa: requiere confirmación de la aplicación.","parameters":{"type":"object","properties":{"form_id":{"type":"string"},"question":{"type":"string"},"required":{"type":"boolean"},"paragraph":{"type":"boolean"}},"required":["form_id","question"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"forms_get","description":"Lee un formulario de Google Forms existente y devuelve sus preguntas y metadatos.","parameters":{"type":"object","properties":{"form_id":{"type":"string"}},"required":["form_id"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"web_search","description":"Busca información pública en Internet en tiempo real mediante Google Search. Úsala para noticias, información actual, precios, empresas, productos, viajes, investigación y cualquier consulta que necesite información web actualizada. Devuelve una respuesta sintetizada con fuentes y citas.","parameters":{"type":"object","properties":{"query":{"type":"string"},"instructions":{"type":"string"}},"required":["query"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"music_reference_analyze","description":"Analiza una referencia musical pública (artista/canciones) usando búsqueda web para extraer BPM/tempo, género, groove, instrumentación, energía y estructura de alto nivel. Sirve para crear una base nueva y original inspirada en rasgos generales, sin copiar melodías, letras, samples ni grabaciones.","parameters":{"type":"object","properties":{"artist":{"type":"string"},"instruction":{"type":"string"}},"required":["artist","instruction"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"web_open","description":"Abre una página web pública y extrae su texto para poder analizarla o resumirla. Úsala cuando el usuario proporcione una URL o pida revisar una página concreta.","parameters":{"type":"object","properties":{"url":{"type":"string"},"max_chars":{"type":"integer","minimum":1000,"maximum":30000}},"required":["url"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"maps_status","description":"Comprueba si Google Maps está configurado en Zar.","parameters":{"type":"object","properties":{},"additionalProperties":False},"strict":True},
    {"type":"function","name":"maps_search","description":"Busca lugares en Google Maps/Places por texto, por ejemplo restaurantes, tiendas, gasolineras o una dirección. Devuelve nombre, dirección, valoración y enlace a Google Maps.","parameters":{"type":"object","properties":{"query":{"type":"string"},"max_results":{"type":"integer","minimum":1,"maximum":10}},"required":["query"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"maps_open_search","description":"Genera y abre una búsqueda universal de Google Maps. No requiere API key y funciona en ordenador y móvil.","parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"maps_directions","description":"Genera y abre indicaciones de Google Maps entre un origen y un destino. Usa esta función para obtener también distancia y duración cuando haya API key configurada.","parameters":{"type":"object","properties":{"origin":{"type":"string"},"destination":{"type":"string"},"travel_mode":{"type":"string","enum":["DRIVE","WALK","BICYCLE","TWO_WHEELER","TRANSIT"]}},"required":["origin","destination"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"calendar_create_confirmed","description":"Crea un evento en Google Calendar únicamente después de que la aplicación haya recibido confirmación explícita del usuario.","parameters":{"type":"object","properties":{"summary":{"type":"string"},"start_iso":{"type":"string"},"end_iso":{"type":"string"},"description":{"type":"string"}},"required":["summary","start_iso","end_iso"],"additionalProperties":False},"strict":True}
]

def execute_tool(name, args):
    if name == "zar_set_task_state":
        try:
            from .context import set_task_state
        except ImportError:
            from context import set_task_state
        data = set_task_state(args.get("intent",""), args.get("object_type",""), args.get("object_id",""), args.get("action",""), args.get("risk",""), args.get("status",""), args.get("summary",""))
        return {"ok": True, "task": data.get("task", {})}
    if name == "zar_get_context":
        try:
            from .context import get_context
        except ImportError:
            from context import get_context
        return {"ok": True, "context": get_context()}
    if name == "save_memory":
        item = remember(args["text"]); return {"ok":True,"message":f"Memoria guardada: {item['text']}"}
    if name == "zar_memory_search":
        try:
            from .knowledge import search
        except ImportError:
            from knowledge import search
        rows = search(args.get("query", ""), args.get("limit", 10))
        return {"ok": True, "results": rows, "message": f"He encontrado {len(rows)} fragmentos en la memoria local."}
    if name == "google_tasks_list":
        try:
            from .google_tasks import list_tasks
            rows = list_tasks(args.get("max_results", 20))
            return {"ok": True, "tasks": rows, "message": f"He encontrado {len(rows)} tareas."}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "message": "No se pudieron consultar las tareas de Google."}
    if name == "google_tasks_search":
        try:
            from .google_tasks import search_tasks
            rows = search_tasks(args.get("query", ""), args.get("max_results", 20))
            return {"ok": True, "tasks": rows, "message": f"He encontrado {len(rows)} tareas que coinciden."}
        except Exception as exc:
            try:
                from .knowledge import search
                rows = search(args.get("query", ""), args.get("max_results", 20))
                return {"ok": True, "offline": True, "tasks": rows, "message": f"Google no está disponible; he buscado en la copia local y he encontrado {len(rows)} resultados."}
            except Exception:
                return {"ok": False, "error": str(exc), "message": "No se pudieron consultar las tareas."}
    if name == "get_local_time":
        n = datetime.now().astimezone(); return {"ok":True,"datetime":n.isoformat(),"human":n.strftime("%A %d/%m/%Y %H:%M:%S")}
    if name == "open_url":
        url=args["url"].strip()
        if not (url.startswith("http://") or url.startswith("https://")): return {"ok":False,"error":"Solo http/https"}
        webbrowser.open(url); return {"ok":True,"message":f"Abierto: {url}"}
    if name == "search_youtube":
        url = f"https://www.youtube.com/results?search_query={quote(args['query'])}"
        try:
            from .context import set_focus, set_media
        except ImportError:
            from context import set_focus, set_media
        set_focus("youtube", args["query"]); set_media("youtube", args["query"], url)
        return {"ok":True,"platform":"youtube","query":args["query"],"url":url,"message":f"YouTube: {args['query']}"}
    if name == "search_spotify":
        url = f"https://open.spotify.com/search/{quote(args['query'])}"
        try:
            from .context import set_focus, set_media
        except ImportError:
            from context import set_focus, set_media
        set_focus("spotify", args["query"]); set_media("spotify", args["query"], url)
        return {"ok":True,"platform":"spotify","query":args["query"],"url":url,"message":f"Spotify: {args['query']}"}
    if name == "video_get_current_project":
        try:
            from .context import get_context, set_focus
            from .video_creator import get_project
        except ImportError:
            from context import get_context, set_focus
            from video_creator import get_project
        ctx=get_context(); pv=ctx.get("last_video_project") or {}; pid=pv.get("id") or (ctx.get("task") or {}).get("object_id")
        project=get_project(pid) if pid else None
        if project:
            set_focus("video", project.get("name","proyecto de vídeo"))
            return {"ok":True,"project":{k:v for k,v in project.items() if k!="_path"}}
        return {"ok":False,"error":"No hay un proyecto de vídeo activo."}
    if name == "video_edit_project":
        try:
            from .context import get_context, set_last_video_project, set_focus
            from .video_creator import get_project, apply_edit_command
        except ImportError:
            from context import get_context, set_last_video_project, set_focus
            from video_creator import get_project, apply_edit_command
        pid=(args.get("project_id") or "").strip()
        if not pid:
            ctx=get_context(); pid=((ctx.get("last_video_project") or {}).get("id") or "")
        if not pid: return {"ok":False,"error":"No hay un proyecto de vídeo activo. Abre o crea uno primero."}
        result=apply_edit_command(pid,args.get("instruction", ""))
        project=result.get("project") or get_project(pid)
        if project:
            set_last_video_project({"id":project.get("id"),"name":project.get("name","" )})
            set_focus("video", project.get("name","proyecto de vídeo"))
        return result
    if name == "video_viral_optimize":
        try:
            from .context import get_context, set_last_video_project, set_focus
            from .video_creator import get_project, viral_optimize
        except ImportError:
            from context import get_context, set_last_video_project, set_focus
            from video_creator import get_project, viral_optimize
        pid=(args.get("project_id") or "").strip()
        if not pid: pid=((get_context().get("last_video_project") or {}).get("id") or "")
        if not pid: return {"ok":False,"error":"No hay un proyecto de vídeo activo."}
        result=viral_optimize(pid,args.get("platform","shorts")); project=result.get("project")
        if project:
            set_last_video_project({"id":project.get("id"),"name":project.get("name","")}); set_focus("video",project.get("name","proyecto de vídeo"))
        return result
    if name == "video_transition_catalog":
        try:
            from .video_creator import transition_catalog
        except ImportError:
            from video_creator import transition_catalog
        return {"ok":True,"transitions":transition_catalog()}
    if name == "file_list":
        try:
            from .file_store import list_files, public_item
        except ImportError:
            from file_store import list_files, public_item
        return {"ok": True, "files": [public_item(x) for x in list_files(args.get("category", ""))]}
    if name == "file_search":
        try:
            from .file_store import search_files, public_item
        except ImportError:
            from file_store import search_files, public_item
        return {"ok": True, "files": [public_item(x) for x in search_files(args.get("query", ""), args.get("category", ""), args.get("limit", 20))]}
    if name == "file_get":
        try:
            from .file_store import get_file, public_item
        except ImportError:
            from file_store import get_file, public_item
        item = get_file(args["file_id"])
        return {"ok": bool(item), "file": public_item(item) if item else None}
    if name == "file_analyze":
        try:
            from .file_analysis import analyze_file
            from .context import set_last_uploaded_file, set_focus, set_task_state
        except ImportError:
            from file_analysis import analyze_file
            from context import set_last_uploaded_file, set_focus, set_task_state
        result = analyze_file(args["file_id"])
        if result.get("ok"):
            item = result.get("file") or {}
            set_last_uploaded_file(item); set_focus("file", item.get("name", "archivo")); set_task_state("analizar archivo", "file", item.get("id", ""), "analizar", "low", "analyzed", f"Archivo analizado: {item.get('name', 'archivo')}")
        return result
    if name == "file_update_metadata":
        try:
            from .file_store import update_file, public_item
            from .context import set_last_uploaded_file, set_focus, set_task_state
        except ImportError:
            from file_store import update_file, public_item
            from context import set_last_uploaded_file, set_focus, set_task_state
        item = update_file(args["file_id"], args.get("category"), args.get("note"))
        if not item:
            return {"ok": False, "error": "No he encontrado ese archivo."}
        set_last_uploaded_file(item); set_focus("file", item.get("name", "archivo")); set_task_state("organizar archivo", "file", item.get("id",""), "clasificar", "low", "file_saved", f"Archivo {item.get('name')} clasificado como {item.get('category')}")
        return {"ok": True, "file": public_item(item), "message": "Archivo organizado y guardado en la memoria de Zar."}
    if name == "gmail_status":
        return gmail_status()
    if name == "gmail_recent":
        return {"ok":True,"messages":recent_messages(args.get("query","in:inbox"), args.get("max_results",10))}
    if name == "gmail_search":
        return {"ok":True,"messages":search_messages(args["query"], args.get("max_results",10))}
    if name == "gmail_get_latest":
        msg = get_latest()
        try:
            from .context import set_active_email, set_focus
        except ImportError:
            from context import set_active_email, set_focus
        if msg:
            set_active_email(msg); set_focus("email", msg.get("subject") or "correo actual")
        return {"ok": True, "message": msg} if msg else {"ok": True, "message": None}
    if name == "gmail_get_current_context":
        try:
            from .context import get_context
        except ImportError:
            from context import get_context
        ctx = get_context()
        return {"ok": True, "active_email": ctx.get("active_email"), "pending_email": ctx.get("pending_email"), "saved_draft_id": ctx.get("saved_draft_id", ""), "last_summary": ctx.get("last_summary", ""), "focus": ctx.get("focus", {}), "task": ctx.get("task", {})}
    if name == "gmail_save_current_draft":
        try:
            from .context import get_context, mark_saved_draft, set_focus
        except ImportError:
            from context import get_context, mark_saved_draft, set_focus
        ctx = get_context(); draft = ctx.get("pending_email")
        if not draft:
            return {"ok": False, "error": "No hay un borrador pendiente en el contexto actual."}
        existing_id = ctx.get("saved_draft_id", "")
        reply_to = draft.get("reply_to_message_id") or None
        thread_id = draft.get("thread_id") or None
        saved = update_draft(existing_id, draft["to"], draft["subject"], draft["body"], reply_to, thread_id) if existing_id else create_draft(draft["to"], draft["subject"], draft["body"], reply_to, thread_id)
        draft_id = saved.get("id", existing_id)
        mark_saved_draft(draft_id); set_focus("email_draft", draft.get("subject") or "borrador actual")
        return {"ok": True, "draft_id": draft_id, "message": "Borrador guardado en Gmail. No se ha enviado.", "draft": draft}
    if name == "gmail_get_message":
        msg = get_message(args["message_id"])
        try:
            from .context import set_active_email, set_focus
        except ImportError:
            from context import set_active_email, set_focus
        if msg:
            set_active_email(msg); set_focus("email", msg.get("subject") or "correo actual")
        return {"ok": True, "message": msg}
    if name == "gmail_prepare_email":
        # Evita reutilizar silenciosamente un destinatario antiguo cuando el usuario
        # acaba de resolver un contacto distinto que no tiene email.
        try:
            from .context import get_context
        except ImportError:
            from context import get_context
        zctx = get_context()
        last_contact = zctx.get("last_contact") or {}
        contact_name = (last_contact.get("name") or "").strip()
        contact_email = (last_contact.get("email") or "").strip()
        user_message = _current_user_message()
        requested_to = (args.get("to") or "").strip()
        if contact_name and not contact_email and requested_to:
            # Si la orden actual menciona/referencia a ese contacto y no proporciona
            # explícitamente un email, no permitimos que el modelo arrastre otro email.
            mentions_contact = contact_name.lower() in user_message.lower()
            anaphoric = bool(re.search(r"\b(él|el|ella|ese|esa|ese contacto|esa persona)\b", user_message.lower()))
            explicit_email = bool(re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", user_message, re.I))
            if (mentions_contact or anaphoric) and not explicit_email:
                return {
                    "ok": False,
                    "error": f"El contacto {contact_name} no tiene ningún correo electrónico guardado. Pide al usuario un email antes de preparar el correo.",
                    "__zar_action__": "CONTACT_EMAIL_MISSING",
                    "contact": last_contact,
                }
        draft = {
            "to": args["to"],
            "subject": args["subject"],
            "body": args["body"],
            "reply_to_message_id": args.get("reply_to_message_id", ""),
            "thread_id": args.get("thread_id", ""),
        }
        try:
            from .context import set_pending_email, set_focus
        except ImportError:
            from context import set_pending_email, set_focus
        set_pending_email(draft); set_focus("email_draft", draft.get("subject") or "borrador actual")
        return {
            "ok": True,
            "__zar_action__": "EMAIL_DRAFT",
            **draft,
            "message": "Borrador preparado para revisión. No se ha enviado."
        }
    if name == "contacts_status":
        try:
            from .google_contacts import contacts_status
        except ImportError:
            from google_contacts import contacts_status
        return contacts_status()
    if name == "contacts_search":
        try:
            from .google_contacts import search_contacts
        except ImportError:
            from google_contacts import search_contacts
        contacts = search_contacts(args.get("query", ""), args.get("limit", 10))
        try:
            from .context import set_last_contact, set_focus
        except ImportError:
            from context import set_last_contact, set_focus
        # Solo fija una referencia anafórica cuando la búsqueda deja un único contacto claro.
        if len(contacts) == 1:
            set_last_contact(contacts[0])
            set_focus("contact", contacts[0].get("name", "contacto"))
        elif len(contacts) == 0:
            set_last_contact(None)
        return {"ok": True, "contacts": contacts}
    if name == "contacts_get":
        try:
            from .google_contacts import get_contact
        except ImportError:
            from google_contacts import get_contact
        contact = get_contact(args["resource_name"])
        try:
            from .context import set_last_contact, set_focus
        except ImportError:
            from context import set_last_contact, set_focus
        set_last_contact(contact)
        set_focus("contact", contact.get("name", "contacto"))
        return {"ok": True, "contact": contact}
    if name == "contacts_create":
        return {"ok": True, "__zar_action__": "CONTACT_ACTION", "action": "crear contacto", "args": {k:v for k,v in args.items() if v not in (None, "")}}
    if name == "contacts_update":
        return {"ok": True, "__zar_action__": "CONTACT_ACTION", "action": "actualizar contacto", "args": args}
    if name == "google_workspace_status":
        try:
            from .google_workspace import workspace_status
        except ImportError:
            from google_workspace import workspace_status
        return workspace_status()
    if name == "drive_search":
        try:
            from .google_workspace import drive_search
        except ImportError:
            from google_workspace import drive_search
        return {"ok": True, "files": drive_search(args["name"], args.get("max_results", 20))}
    if name == "drive_list_recent":
        try:
            from .google_workspace import drive_list
        except ImportError:
            from google_workspace import drive_list
        return {"ok": True, "files": drive_list(None, args.get("max_results", 20))}
    if name == "docs_create":
        return {"ok": True, "__zar_action__": "WORKSPACE_ACTION", "service": "Google Docs", "action": "crear documento", "args": {"title": args["title"], "text": args.get("text", "")}}
    if name == "docs_append":
        return {"ok": True, "__zar_action__": "WORKSPACE_ACTION", "service": "Google Docs", "action": "añadir texto al documento", "args": {"document_id": args["document_id"], "text": args["text"]}}
    if name == "sheets_create":
        return {"ok": True, "__zar_action__": "WORKSPACE_ACTION", "service": "Google Sheets", "action": "crear hoja de cálculo", "args": {"title": args["title"]}}
    if name == "sheets_read":
        try:
            from .google_workspace import sheets_read
        except ImportError:
            from google_workspace import sheets_read
        return sheets_read(args["spreadsheet_id"], args["range_a1"])
    if name == "sheets_write":
        return {"ok": True, "__zar_action__": "WORKSPACE_ACTION", "service": "Google Sheets", "action": "escribir datos", "args": {"spreadsheet_id": args["spreadsheet_id"], "range_a1": args["range_a1"], "values": args["values"]}}
    if name == "slides_create":
        return {"ok": True, "__zar_action__": "WORKSPACE_ACTION", "service": "Google Slides", "action": "crear presentación", "args": {"title": args["title"]}}
    if name == "forms_create":
        return {"ok": True, "__zar_action__": "WORKSPACE_ACTION", "service": "Google Forms", "action": "crear formulario", "args": {"title": args["title"], "description": args.get("description", "")}}
    if name == "forms_add_question":
        return {"ok": True, "__zar_action__": "WORKSPACE_ACTION", "service": "Google Forms", "action": "añadir pregunta", "args": {"form_id": args["form_id"], "question": args["question"], "required": args.get("required", False), "paragraph": args.get("paragraph", False)}}
    if name == "forms_get":
        try:
            from .google_workspace import forms_get
        except ImportError:
            from google_workspace import forms_get
        return {"ok": True, "form": forms_get(args["form_id"])}
    if name == "calendar_status":
        return calendar_status()
    if name == "calendar_upcoming":
        return {"ok":True,"events":upcoming_events(args.get("days",7), args.get("max_results",10))}
    if name == "web_search":
        try:
            from .web_search import google_web_search
        except ImportError:
            from web_search import google_web_search
        return google_web_search(args.get("query", ""), args.get("instructions", ""))
    if name == "music_reference_analyze":
        try:
            from .music_reference import analyze_reference
        except ImportError:
            from music_reference import analyze_reference
        return analyze_reference(args.get("instruction", ""), args.get("artist", ""))
    if name == "web_open":
        try:
            from .web_search import fetch_webpage
        except ImportError:
            from web_search import fetch_webpage
        return fetch_webpage(args.get("url", ""), int(args.get("max_chars", 18000)))
    if name == "maps_status":
        try:
            from .maps import maps_status
            from .config import load
        except ImportError:
            from maps import maps_status
            from config import load
        return maps_status(load())
    if name == "maps_search":
        try:
            from .maps import maps_search_text
            from .config import load
        except ImportError:
            from maps import maps_search_text
            from config import load
        return maps_search_text(args["query"], args.get("max_results", 5), load())
    if name == "maps_open_search":
        from urllib.parse import quote
        url = f"https://www.google.com/maps/search/?api=1&query={quote(args['query'])}"
        webbrowser.open(url)
        return {"ok": True, "query": args["query"], "url": url}
    if name == "maps_directions":
        try:
            from .maps import maps_route
            from .config import load
        except ImportError:
            from maps import maps_route
            from config import load
        result = maps_route(args["origin"], args["destination"], args.get("travel_mode", "DRIVE"), load())
        if result.get("maps_url"):
            webbrowser.open(result["maps_url"])
        return result
    if name == "calendar_create_confirmed":
        e = create_event(args["summary"], args["start_iso"], args["end_iso"], args.get("description",""))
        return {"ok":True,"id":e.get("id"),"summary":e.get("summary"),"htmlLink":e.get("htmlLink")}
    return {"ok":False,"error":f"Herramienta desconocida: {name}"}
