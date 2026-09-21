from flask import Flask, render_template, request, jsonify, redirect, session, send_file
import threading
import webbrowser
import re
import requests
import os
import secrets
import time
import json
import mimetypes
import html as html_lib
import uuid
from datetime import datetime, timezone
from .user_scope import set_current_user, get_current_user, anonymous_id, user_id_for_email
from pathlib import Path
from .cloud_auth import authorization_url, finish_oauth, connected, auth_status, get_credentials
from .youtube_auth import authorization_url as youtube_authorization_url, finish_oauth as finish_youtube_oauth, status as youtube_auth_status
from .agent import respond, summarize_email, draft_reply_email, revise_email_draft
from .tools import TOOL_DEFINITIONS, execute_tool
from .memory import memories, remember, delete_memory, history, add_message, conversation, add_conversation_message, clear_conversation, list_conversations, get_conversation_archive
from .config import load, save
from .google_calendar import calendar_status
from .gmail import gmail_status
from .google_workspace import workspace_status
from .google_backup import start_google_backup, backup_status, maybe_start_google_backup
from .context import get_context, set_active_email, set_pending_email, mark_saved_draft, clear_pending, set_summary, reset_context, set_pending_calendar, clear_pending_calendar, set_focus, clear_focus, set_task_state, clear_task_state, set_last_uploaded_file, set_pending_workspace, clear_pending_workspace, set_last_contact, set_media, set_last_video_project
from .file_store import save_upload, get_file, list_files, search_files, public_item, delete_file, files_dir
from .knowledge import context_for as memory_context_for, search as search_memory, stats as memory_stats, memory_insights, index_file_from_disk, bootstrap_from_legacy
from .memory3 import stats as memory3_stats, recent as memory3_recent, search as memory3_search, reindex_existing as memory3_reindex
from .web_search import search_inspiration_images, analyze_inspiration_image
from .deep_research import start_research, wait_for_research, save_report, list_reports, get_report, get_research, extract_report
from .video_creator import create_project, list_projects, get_project, project_path, add_media as video_add_media, generate_music, render_project, media_path, set_project, update_media, delete_media, move_media, transition_catalog, apply_edit_command, viral_optimize, add_text_overlay, update_text_overlay, delete_text_overlay
from .audio_studio import create_project as audio_create_project, list_projects as audio_list_projects, save_settings as audio_save_settings, render_base as audio_render_base, apply_voice_effect as audio_apply_voice_effect, audio_command as interpret_audio_command
from .studio_agent import interpret as interpret_studio_command
from .voice_transcription import transcribe_audio
from .voice_tts import synthesize
from .youtube import status as youtube_status, upload as youtube_upload, video_status as youtube_video_status
from app.youtube_publish import register_youtube

app = Flask(__name__)
register_youtube(app)

# Clave de sesión estable: si Railway reinicia el proceso durante un OAuth,
# la sesión y el estado PKCE no se invalidan. Si no hay variable de entorno,
# Zar conserva una clave propia en el almacenamiento persistente.
_SESSION_SECRET_FILE = Path(os.environ.get('ZAR_DATA_DIR', '/data')) / 'zar_session_secret.txt'
_session_secret = os.environ.get('ZAR_SESSION_SECRET', '').strip()
if not _session_secret:
    try:
        _SESSION_SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
        if _SESSION_SECRET_FILE.exists():
            _session_secret = _SESSION_SECRET_FILE.read_text(encoding='utf-8').strip()
        if not _session_secret:
            _session_secret = secrets.token_urlsafe(48)
            _SESSION_SECRET_FILE.write_text(_session_secret, encoding='utf-8')
    except Exception:
        _session_secret = secrets.token_urlsafe(48)
app.secret_key = _session_secret
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)


def _user_scope_id():
    uid = session.get("zar_user_id")
    if uid:
        return uid
    browser_id = session.get("zar_browser_id")
    if not browser_id:
        browser_id = uuid.uuid4().hex
        session["zar_browser_id"] = browser_id
    uid = anonymous_id(browser_id)
    session["zar_user_id"] = uid
    return uid

def _migrate_legacy_owner():
    """Adopt the pre-v27.38 single-user data only for the first browser that opens ZAR."""
    marker = Path(os.environ.get('ZAR_DATA_DIR','/data')) / 'legacy_owner_browser.txt'
    legacy = Path(os.environ.get('ZAR_DATA_DIR','/data')) / 'google_token.json'
    if marker.exists() or not legacy.exists():
        return
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(session.get('zar_browser_id',''), encoding='utf-8')
        uid = _user_scope_id()
        target = Path(os.environ.get('ZAR_DATA_DIR','/data')) / 'users' / uid
        target.mkdir(parents=True, exist_ok=True)
        for name in ('google_token.json','memory.json','chat_history.json','conversation.json','active_context.json'):
            src = Path(os.environ.get('ZAR_DATA_DIR','/data')) / name
            dst = target / name
            if src.exists() and not dst.exists():
                src.replace(dst)
    except Exception:
        pass

@app.before_request
def _set_scope():
    uid = _user_scope_id()
    set_current_user(uid)
    _migrate_legacy_owner()


def _canonical_origin():
    """Return Zar's canonical public origin for browser/OAuth redirects."""
    raw = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if raw:
        return raw
    raw = os.environ.get("GOOGLE_REDIRECT_URI", "").strip().rstrip("/")
    if raw and raw.endswith("/oauth2callback"):
        return raw[:-len("/oauth2callback")].rstrip("/")
    # Railway sits behind a reverse proxy. request.host_url can otherwise be
    # built with the internal HTTP scheme even though the public browser URL is
    # HTTPS, producing Google's exact error: redirect_uri_mismatch.
    host = request.headers.get("X-Forwarded-Host", "").split(",")[0].strip() or request.host
    proto = request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip() or request.scheme
    if host:
        return f"{proto}://{host}"
    return ""

def _google_redirect_uri():
    """Build the exact public callback URI used by both OAuth steps."""
    explicit = os.environ.get("GOOGLE_REDIRECT_URI", "").strip()
    if explicit:
        return explicit.rstrip("/")
    origin = _canonical_origin().rstrip("/")
    if origin:
        return origin + "/oauth2callback"
    return request.host_url.rstrip("/") + "/oauth2callback"

def _canonical_redirect_if_needed():
    origin = _canonical_origin()
    if not origin:
        return None
    try:
        from urllib.parse import urlparse
        target = urlparse(origin)
        if request.scheme == target.scheme and request.host == target.netloc:
            return None
    except Exception:
        return None
    return redirect(origin + request.path + (("?" + request.query_string.decode()) if request.query_string else ""))

_OAUTH_PENDING_FILE = Path(os.environ.get('ZAR_DATA_DIR', '/data')) / 'oauth_pending.json'

def _save_oauth_pending(provider, state, verifier, redirect_uri=None):
    """Persist OAuth transactions independently of the browser session.

    A user can have several Zar tabs/windows open, and Railway may route the
    OAuth callback without the original Flask session cookie. Store each
    transaction by its unique state instead of keeping only one state per
    provider. This prevents a second authorization flow from invalidating the
    first one.
    """
    try:
        _OAUTH_PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if _OAUTH_PENDING_FILE.exists():
            try:
                data = json.loads(_OAUTH_PENDING_FILE.read_text(encoding='utf-8')) or {}
            except Exception:
                data = {}
        if not isinstance(data, dict):
            data = {}
        data[state] = {'provider': provider, 'state': state, 'verifier': verifier, 'redirect_uri': redirect_uri, 'user_id': get_current_user(), 'created_at': time.time()}
        # Keep only recent transactions.
        cutoff = time.time() - 15 * 60
        data = {k: v for k, v in data.items() if isinstance(v, dict) and float(v.get('created_at', 0) or 0) >= cutoff}
        tmp = _OAUTH_PENDING_FILE.with_suffix('.tmp')
        tmp.write_text(json.dumps(data), encoding='utf-8')
        tmp.replace(_OAUTH_PENDING_FILE)
    except Exception:
        pass

def _load_oauth_pending(provider, state=None):
    try:
        data = json.loads(_OAUTH_PENDING_FILE.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            return {}
        # New format: every OAuth transaction is keyed by its state.
        if state and isinstance(data.get(state), dict):
            item = data[state]
            if item.get('provider') == provider:
                return item
        # Backwards compatibility with the previous provider-keyed format.
        legacy = data.get(provider)
        if isinstance(legacy, dict):
            return legacy
    except Exception:
        pass
    return {}

def _clear_oauth_pending(provider, state=None):
    try:
        data = json.loads(_OAUTH_PENDING_FILE.read_text(encoding='utf-8')) if _OAUTH_PENDING_FILE.exists() else {}
        if not isinstance(data, dict):
            return
        if state:
            item = data.get(state)
            if isinstance(item, dict) and item.get('provider') == provider:
                data.pop(state, None)
        else:
            # Legacy cleanup.
            data.pop(provider, None)
        _OAUTH_PENDING_FILE.write_text(json.dumps(data), encoding='utf-8')
    except Exception:
        pass

TEMPLATE_OAUTH_SUCCESS = "<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta name='theme-color' content='#090807'><title>Zar · Conexión correcta</title><style>*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#090807;color:#f3ece4;font-family:Inter,system-ui,sans-serif;overflow:hidden}.bg{position:fixed;inset:0;background:linear-gradient(90deg,rgba(9,8,7,.2),rgba(9,8,7,.82)),url('/static/zar-dog.png') left center/cover no-repeat;filter:brightness(.7) saturate(.75);transform:scale(1.03)}.veil{position:fixed;inset:0;background:radial-gradient(circle at 50% 35%,rgba(215,169,100,.16),transparent 38%),linear-gradient(180deg,rgba(7,6,5,.25),rgba(7,6,5,.84))}.box{position:relative;width:min(720px,calc(100% - 30px));padding:32px;border:1px solid rgba(215,169,100,.5);border-radius:26px;background:rgba(20,15,11,.76);backdrop-filter:blur(18px);box-shadow:0 30px 100px rgba(0,0,0,.62);text-align:center}.dog{width:92px;height:76px;object-fit:cover;object-position:center 38%;border-radius:20px;margin:0 auto 12px;display:block}.ok{width:64px;height:64px;border-radius:50%;display:grid;place-items:center;margin:6px auto 12px;border:1px solid rgba(215,169,100,.65);background:rgba(215,169,100,.12);font-size:34px;color:#e5c58e}h1{font:700 38px Georgia,serif;color:#ead0a5;margin:0 0 8px}p{color:#b9aea3;font-size:14px;line-height:1.55;margin:8px 0}.services{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:20px 0}.svc{padding:11px 7px;border:1px solid #4a3828;border-radius:12px;background:rgba(8,7,6,.55);color:#d8cabb}.svc.ok{border-color:rgba(113,167,109,.55)}.svc.pending{border-color:rgba(185,145,76,.5)}.svc span{display:block;font-size:20px;margin-bottom:4px}.svc b{display:block;font-size:10px}.svc small{display:block;font-size:8px;color:#8e8379;margin-top:3px}.btn{display:inline-block;margin-top:12px;padding:12px 24px;border:1px solid #9d713c;border-radius:13px;background:linear-gradient(180deg,#ddb776,#bd8a4c);color:#1a120a;font-weight:800;text-decoration:none}small.note{display:block;margin-top:10px;color:#81766d}@media(max-width:560px){.box{padding:24px 16px}.services{grid-template-columns:repeat(2,1fr)}h1{font-size:32px}}</style></head><body><div class='bg'></div><div class='veil'></div><div class='box'><img class='dog' src='/static/zar-dog.png'><div class='ok'>✓</div><h1>Conexión correcta</h1><p><strong>__LABEL__ conectado</strong></p><p>__DETAIL__</p><div class='services'>__CHIPS__</div><a class='btn' href='/'>Abrir Zar →</a><small class='note'>Volviendo automáticamente a Zar…</small></div><script>setTimeout(function(){try{if(window.opener&&!window.opener.closed){window.opener.postMessage({type:'zar-oauth-success'},window.location.origin);try{window.opener.focus()}catch(e){}setTimeout(function(){try{window.close()}catch(e){}},300);return}}catch(e){}window.location.href='/'},1100);</script></body></html>"

def _oauth_success_page(provider):
    label = 'Google' if provider == 'google' else 'YouTube'
    if provider == 'google':
        detail = 'Tu cuenta de Google está conectada. Zar ha guardado la autorización y puede conservar una copia local consultable de tus datos permitidos.'
        services = [('✉️','Gmail'),('📅','Calendar'),('☁️','Drive'),('📄','Docs'),('📊','Sheets'),('📽️','Slides'),('📝','Forms'),('👤','Contactos'),('✅','Tareas')]
    else:
        detail = 'Tu cuenta de YouTube está conectada. Ya puedes publicar desde Zar Studio.'
        services = [('▶️','YouTube')]
    missing = set(auth_status().get('missing_scopes', [])) if provider == 'google' else set()
    scope_map = {'Gmail':'https://www.googleapis.com/auth/gmail.readonly','Calendar':'https://www.googleapis.com/auth/calendar','Drive':'https://www.googleapis.com/auth/drive.readonly','Docs':'https://www.googleapis.com/auth/documents','Sheets':'https://www.googleapis.com/auth/spreadsheets','Slides':'https://www.googleapis.com/auth/presentations','Forms':'https://www.googleapis.com/auth/forms.body','Contactos':'https://www.googleapis.com/auth/contacts','Tareas':'https://www.googleapis.com/auth/tasks.readonly'}
    chips = ''.join("<div class='svc %s'><span>%s</span><b>%s</b><small>%s</small></div>" % ('pending' if scope_map.get(name) in missing else 'ok', icon, name, 'Pendiente' if scope_map.get(name) in missing else 'Activo') for icon,name in services)
    html = TEMPLATE_OAUTH_SUCCESS.replace('__LABEL__', html_lib.escape(label)).replace('__DETAIL__', html_lib.escape(detail)).replace('__CHIPS__', chips)
    return html

# Memoria persistente local: migra el historial/archivos antiguos una sola vez.
try:
    bootstrap_from_legacy(memories(), history(), conversation(), list_files())
except Exception:
    pass

# Background job store for Cloud: long AI/Gmail operations do not hold an HTTP request open.
JOB_DIR = Path(os.environ.get("ZAR_JOB_DIR", "/data/jobs"))
JOB_DIR.mkdir(parents=True, exist_ok=True)

def _remember_turn(role, content):
    add_message(role, content)
    add_conversation_message(role, content)

def _ctx():
    return get_context()

def _set_email(email):
    set_active_email(email)

def _set_pending(draft):
    set_pending_email(draft)

def _job_path(job_id):
    return JOB_DIR / f"{job_id}.json"

def _write_job(job_id, status, reply=None, error=None, action=None, user_id=None):
    payload = {"status": status}
    if user_id: payload["user_id"] = user_id
    if action is not None:
        payload["action"] = action
    if reply is not None:
        payload["reply"] = reply
    if error is not None:
        payload["error"] = error
    path = _job_path(job_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)

def _read_job(job_id):
    path = _job_path(job_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

def _run_chat_job(job_id, msg, user_id):
    set_current_user(user_id)
    try:
        reply = _process_chat_message(msg)
        action = (_ctx().get("last_media") or None)
        _write_job(job_id, "done", reply=reply, action=( {"type":"open_url","url":action.get("url"),"platform":action.get("platform"),"query":action.get("query")} if action and action.get("url") else None ))
    except Exception as exc:
        _write_job(job_id, "error", error=str(exc))


def _is_noreply(address):
    """Detecta direcciones automáticas que suelen no aceptar respuestas."""
    addr = (address or "").strip().lower()
    if "<" in addr and ">" in addr:
        addr = addr.split("<", 1)[1].split(">", 1)[0].strip()
    local = addr.split("@", 1)[0] if "@" in addr else addr
    return local.startswith(("noreply", "no-reply", "donotreply", "do-not-reply", "do_not_reply"))


def _email_card(draft, question=True):
    blocked = _is_noreply(draft.get("to", ""))
    warning = "⚠️ Atención: el destinatario parece una dirección automática (noreply). Es posible que no acepte respuestas. Zar no lo enviará con un simple «sí»; usa «enviar de todos modos» solo si estás seguro." if blocked else ""
    tail = (
        "\n\n" + warning if warning else ""
    )
    if question:
        tail += "\n\n¿Quieres que la envíe?\n\nResponde «sí» para enviarla o «cancelar» para descartarla."
    return (
        f"✉️ He preparado esta respuesta, pero NO la he enviado.\n\n"
        f"Para: {draft['to']}\n"
        f"Asunto: {draft['subject']}\n\n"
        f"{draft['body']}" + tail
    )


def _pending_email_from(draft):
    return {
        "to": draft["to"],
        "subject": draft["subject"],
        "body": draft["body"],
        "reply_to_message_id": draft.get("reply_to_message_id", ""),
        "thread_id": draft.get("thread_id", ""),
        "noreply": _is_noreply(draft.get("to", ""))
    }


def _execute_contact_action(pending):
    try:
        from . import google_contacts as gc
    except ImportError:
        import google_contacts as gc
    action = pending.get("action", "")
    args = pending.get("args") or {}
    if action == "crear contacto":
        return gc.create_contact(args.get("name", ""), args.get("email", ""), args.get("phone", ""), args.get("company", ""))
    if action == "actualizar contacto":
        return gc.update_contact(args.get("resource_name", ""), args.get("etag", ""), args.get("name"), args.get("email"), args.get("phone"), args.get("company"))
    raise RuntimeError(f"Acción de contacto no soportada: {action}")


def _normalize_text(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())

def _looks_like_draft_edit(text):
    t = _normalize_text(text)
    phrases = (
        "hazlo más formal", "hazlo mas formal", "hazlo más corto", "hazlo mas corto",
        "hazlo más breve", "hazlo mas breve", "hazlo más cercano", "hazlo mas cercano",
        "hazlo más profesional", "hazlo mas profesional", "hazlo más natural", "hazlo mas natural",
        "cámbialo", "cambialo", "cambia el tono", "cambia el saludo", "cambia la despedida",
        "haz una nueva versión", "haz una nueva version", "mejora la respuesta", "mejorala", "mejórala",
        "modifica el borrador", "revisa el borrador", "mejora el borrador", "edita el borrador",
        "añade ", "anade ", "agrega ", "quita ", "elimina ", "cambia ", "pon que ", "di que ",
        "dile que ", "haz que diga ", "que diga ", "quiero que diga ", "pon también ", "pon tambien "
    )
    return any(p in t for p in phrases)

def _looks_like_save_draft(text):
    t = _normalize_text(text)
    phrases = (
        "guardar como borrador", "guárdalo como borrador", "guardalo como borrador",
        "guárdala como borrador", "guardala como borrador",
        "guárdalo de nuevo como borrador", "guardalo de nuevo como borrador",
        "guárdala de nuevo como borrador", "guardala de nuevo como borrador",
        "guarda el borrador", "guardar el borrador", "guárdame el borrador", "guardame el borrador",
        "déjalo como borrador", "dejalo como borrador", "déjala como borrador", "dejala como borrador",
        "déjame el borrador", "dejame el borrador", "consérvalo como borrador", "conservalo como borrador",
        "consérvala como borrador", "conservala como borrador", "quiero guardar el borrador",
        "guárdalo", "guardalo", "guárdala", "guardala", "guardar esto", "guardar la respuesta"
    )
    # Las formas cortas solo se aceptan con un borrador pendiente para evitar falsos positivos.
    return any(p in t for p in phrases)

def _looks_like_send(text):
    t = _normalize_text(text)
    return t in {"sí", "si", "enviar", "envíalo", "envialo", "confirma", "confirmar", "adelante", "mándalo", "mandalo", "envía", "envia"}

def _looks_like_cancel(text):
    t = _normalize_text(text)
    return t in {"cancelar", "cancela", "no enviar", "no lo envíes", "no lo envies", "descarta", "descartalo", "descártalo", "olvídalo", "olvidalo"}

def _contextual_gmail_intent(msg, ctx, pending_email, last_email):
    """Resuelve referencias naturales a email sin exigir que el usuario repita 'correo'."""
    t = _normalize_text(msg)
    has_email = bool(last_email or pending_email)
    if not has_email:
        return None
    # Comprensión del correo actual.
    if any(q in t for q in (
        "qué quiere", "que quiere", "qué me pide", "que me pide", "qué me está pidiendo",
        "que me esta pidiendo", "qué dice", "que dice", "qué necesita", "que necesita",
        "de qué va", "de que va", "de qué trata", "de que trata", "qué hago con esto",
        "que hago con esto", "qué hago", "que hago", "explícamelo", "explicamelo", "explícame"
    )):
        return "summarize"
    # Orden breve para resumir el contexto.
    if t in {"resume", "resumen", "resúmelo", "resumelo", "haz un resumen", "hazme un resumen", "dímelo resumido", "dimelo resumido"}:
        return "summarize"
    # Redacción contextual sin mencionar correo/email.
    if any(v in t for v in ("respóndele", "respondele", "contéstale", "contestale", "redáctale", "redactale", "contesta", "responde")) and not ("gmail" in t or "correo" in t or "email" in t):
        instruction = re.sub(r"^(?:y\s+)?(?:respóndele|respondele|contéstale|contestale|redáctale|redactale|contesta|responde)\s*", "", t)
        instruction = instruction.strip(" .,:;\"“”' ")
        if instruction:
            if instruction.startswith("que "):
                instruction = instruction[3:].strip()
            return {"type":"draft_context", "instruction":instruction}
    return None

def _auth_enabled():
    return bool(os.environ.get("ZAR_ACCESS_PASSWORD"))

def _authorized():
    return (not _auth_enabled()) or bool(session.get("zar_auth"))

@app.before_request
def _guard():
    allowed = {"login","health","oauth2callback","connect_google","connect_gmail"}
    if request.endpoint in allowed or request.path.startswith("/static/"):
        return None
    if _auth_enabled() and not _authorized():
        if request.path.startswith("/api/"):
            return jsonify({"error":"No autenticado"}), 401
        return redirect("/login")

@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "zar"})

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        if secrets.compare_digest(request.form.get("password", ""), os.environ.get("ZAR_ACCESS_PASSWORD", "")):
            session["zar_auth"] = True
            return redirect("/")
        return "<h2>Contraseña incorrecta</h2><p><a href=\"/login\">Volver</a></p>", 401
    return """<!doctype html><html lang=\"es\"><head><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><meta name=\"theme-color\" content=\"#090807\"><style>*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#090807;color:#f3ece4;font-family:Inter,system-ui,sans-serif;overflow:hidden}.bg{position:fixed;inset:0;background:linear-gradient(90deg,rgba(9,8,7,.18),rgba(9,8,7,.7)),url('/static/zar-dog.png') left center/cover no-repeat;filter:brightness(.7) saturate(.75);transform:scale(1.03)}.veil{position:fixed;inset:0;background:radial-gradient(circle at 30% 45%,rgba(215,169,100,.14),transparent 38%),linear-gradient(180deg,rgba(7,6,5,.2),rgba(7,6,5,.72))}.box{position:relative;width:min(420px,calc(100% - 34px));padding:26px;border:1px solid rgba(215,169,100,.45);border-radius:22px;background:rgba(20,15,11,.55);backdrop-filter:blur(18px);box-shadow:0 30px 90px rgba(0,0,0,.55);text-align:center}.dog{width:96px;height:78px;object-fit:cover;object-position:center 38%;border-radius:20px;margin:0 auto 8px;display:block;box-shadow:0 14px 35px rgba(0,0,0,.5)}h1{font:700 42px Georgia,serif;color:#ead0a5;margin:0}p{color:#b9aea3;font-size:13px}.field{position:relative;margin:18px 0}.field input{width:100%;height:52px;padding:0 15px;border:1px solid #5a4633;border-radius:13px;background:rgba(10,8,6,.56);color:#fff;outline:none}.field input:focus{border-color:#d7a964}.btn{width:100%;height:52px;border:1px solid #9d713c;border-radius:13px;background:linear-gradient(180deg,#ddb776,#bd8a4c);color:#1a120a;font-weight:700;font-size:15px;cursor:pointer}.tag{margin-top:12px;font-size:10px;letter-spacing:.2em;color:#c99a5d}</style></head><body><div class=\"bg\"></div><div class=\"veil\"></div><div class=\"box\"><img class=\"dog\" src=\"/static/zar-dog.png\"><h1>Zar</h1><div class=\"tag\">SIEMPRE CONTIGO</div><p>Acceso seguro a tu agente personal.</p><form method=\"post\"><div class=\"field\"><input name=\"password\" type=\"password\" placeholder=\"Introduce tu contraseña\" autofocus></div><button class=\"btn\" type=\"submit\">Entrar →</button></form></div></body></html>"""

@app.get("/oauth2callback")
def oauth2callback():
    state = request.args.get("state", "")
    code = request.args.get("code", "")
    provider = session.get("oauth_provider")
    pending = _load_oauth_pending(provider or "google", state) if state else {}
    if not pending and state:
        pending = _load_oauth_pending("google", state)
        if pending:
            provider = "google"
        else:
            pending = _load_oauth_pending("youtube", state)
            if pending:
                provider = "youtube"
    provider = provider or "google"
    if pending.get("user_id"):
        session["zar_user_id"] = pending.get("user_id")
        set_current_user(pending.get("user_id"))
    # Prefer the transaction matched by the callback state. The browser session
    # is only a fallback; this makes OAuth resilient to Railway restarts, tabs,
    # popups and cookie/session changes during the Google redirect.
    expected = pending.get("state") or session.get("oauth_state")
    verifier = pending.get("verifier") or session.get("oauth_code_verifier")
    if not code or not expected or not state or not secrets.compare_digest(state, expected):
        return _oauth_error_page('Estado OAuth inválido o caducado. Vuelve a Zar e inicia la conexión de Google de nuevo.') , 400
    try:
        if provider == "youtube":
            finish_youtube_oauth(state, code, verifier)
            _clear_oauth_pending('youtube', state)
            session.pop("oauth_provider", None)
            session.pop("oauth_state", None)
            session.pop("oauth_code_verifier", None)
            return _oauth_success_page('youtube')
        finish_oauth(state, code, verifier, pending.get('redirect_uri'), user_id=pending.get('user_id') or get_current_user())
        # Vincula esta sesión al correo Google real y mueve su token al espacio aislado por cuenta.
        try:
            from .cloud_auth import get_account_email, get_credentials, _token_file
            creds = get_credentials(auto_refresh=True, user_id=pending.get('user_id') or get_current_user())
            google_email = get_account_email(creds)
            if google_email:
                old_uid = pending.get('user_id') or get_current_user()
                new_uid = user_id_for_email(google_email)
                old_path = _token_file(old_uid)
                new_path = _token_file(new_uid)
                new_path.parent.mkdir(parents=True, exist_ok=True)
                if old_path.exists() and old_path != new_path:
                    old_path.replace(new_path)
                session['zar_user_id'] = new_uid
                session['google_account_email'] = google_email
                set_current_user(new_uid)
        except Exception:
            pass
        # Tras una conexión/reautorización correcta, crear una copia de seguridad
        # independiente de Google en el almacenamiento persistente de Zar.
        try:
            start_google_backup("google_connected")
        except Exception:
            pass
        _clear_oauth_pending('google', state)
        session.pop("oauth_provider", None)
        session.pop("oauth_state", None)
        session.pop("oauth_code_verifier", None)
        return _oauth_success_page('google')
    except Exception as exc:
        return _oauth_error_page(f'No se pudo conectar {html_lib.escape("YouTube" if provider == "youtube" else "Google")}: {html_lib.escape(str(exc))}'), 500

def _oauth_error_page(message):
    return f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#090807"><title>Zar · Error de conexión</title><style>*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#090807;color:#f3ece4;font-family:Inter,system-ui,sans-serif}}.box{{width:min(520px,calc(100% - 32px));padding:32px;border:1px solid rgba(215,169,100,.45);border-radius:24px;background:rgba(20,15,11,.82);box-shadow:0 30px 100px rgba(0,0,0,.6);text-align:center}}h1{{font:700 34px Georgia,serif;color:#ead0a5;margin:0 0 12px}}p{{color:#b9aea3;line-height:1.55}}.btn{{display:inline-block;margin-top:12px;padding:12px 22px;border:1px solid #9d713c;border-radius:13px;background:linear-gradient(180deg,#ddb776,#bd8a4c);color:#1a120a;font-weight:700;text-decoration:none}}</style></head><body><div class="box"><h1>⚠️ No se pudo conectar</h1><p>{message}</p><a class="btn" href="/">Volver a Zar</a></div></body></html>'''

def _google_login_page(status=None):
    detail = "Inicia sesión con tu cuenta de Google para activar Gmail, Calendar, Drive, Docs, Sheets, Slides, Forms y Contactos."
    if status and status.get("error"):
        detail += " La autorización anterior necesita volver a iniciarse."
    detail = html_lib.escape(detail)
    return f"""<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta name='theme-color' content='#090807'><title>Zar · Iniciar sesión</title><style>*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#090807;color:#f3ece4;font-family:Inter,system-ui,sans-serif;overflow:hidden}}.bg{{position:fixed;inset:0;background:linear-gradient(90deg,rgba(9,8,7,.2),rgba(9,8,7,.82)),url('/static/zar-dog.png') left center/cover no-repeat;filter:brightness(.7) saturate(.75);transform:scale(1.03)}}.veil{{position:fixed;inset:0;background:radial-gradient(circle at 50% 35%,rgba(215,169,100,.16),transparent 38%),linear-gradient(180deg,rgba(7,6,5,.25),rgba(7,6,5,.84))}}.box{{position:relative;width:min(590px,calc(100% - 32px));padding:36px 32px;border:1px solid rgba(215,169,100,.5);border-radius:26px;background:rgba(20,15,11,.72);backdrop-filter:blur(18px);box-shadow:0 30px 100px rgba(0,0,0,.62);text-align:center}}.dog{{width:105px;height:86px;object-fit:cover;object-position:center 38%;border-radius:22px;margin:0 auto 14px;display:block;box-shadow:0 14px 35px rgba(0,0,0,.5)}}h1{{font:700 42px Georgia,serif;color:#ead0a5;margin:0 0 8px}}.sub{{color:#b9aea3;font-size:14px;line-height:1.55;margin:0 auto 22px;max-width:480px}}.googleBtn{{display:inline-flex;align-items:center;justify-content:center;gap:10px;min-width:270px;height:52px;padding:0 22px;border:1px solid #9d713c;border-radius:14px;background:linear-gradient(180deg,#ddb776,#bd8a4c);color:#1a120a;font-weight:800;font-size:15px;cursor:pointer}}.services{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:22px}}.svc{{padding:10px 7px;border:1px solid #33271e;border-radius:12px;background:rgba(8,7,6,.5);color:#7f756c;font-size:10px}}.svc span{{display:block;font-size:20px;margin-bottom:5px;filter:grayscale(1)}}.tag{{margin-top:18px;font-size:9px;letter-spacing:.2em;color:#c99a5d}}@media(max-width:560px){{.box{{padding:28px 18px}}.services{{grid-template-columns:repeat(2,1fr)}}h1{{font-size:34px}}}}</style></head><body><div class='bg'></div><div class='veil'></div><div class='box'><img class='dog' src='/static/zar-dog.png'><h1>Hola, soy Zar</h1><p class='sub'>{detail}</p><button class='googleBtn' onclick="loginGoogle()">G&nbsp;&nbsp; Continuar con Google</button><div class='services'><div class='svc'><span>✉️</span>Gmail</div><div class='svc'><span>📅</span>Calendar</div><div class='svc'><span>☁️</span>Drive</div><div class='svc'><span>📄</span>Docs</div><div class='svc'><span>📊</span>Sheets</div><div class='svc'><span>📽️</span>Slides</div><div class='svc'><span>📝</span>Forms</div><div class='svc'><span>👤</span>Contactos</div></div><div class='tag'>ZAR · AGENTE IA PERSONAL</div></div><script>function loginGoogle(){{window.location.href='/connect/google?force=1';}}</script></body></html>"""

@app.get("/")
def home():
    status = auth_status()
    if status.get("connected"):
        try:
            maybe_start_google_backup(24)
        except Exception:
            pass
    if not status.get("connected"):
        return _google_login_page(status)
    return render_template("index.html")

@app.get("/api/maps/search")
def maps_search_endpoint():
    try:
        from .maps import maps_search_text
    except ImportError:
        from maps import maps_search_text
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"ok": False, "error": "Falta la búsqueda."}), 400
    try:
        return jsonify(maps_search_text(q, 8, load()))
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502

@app.get("/api/state")
def state():
    cfg = load()
    google_ready = True
    google_info = auth_status()
    google_authorized = bool(google_info.get("connected"))
    return jsonify({
        "config": {
            "provider": cfg["provider"],
            "api_model": cfg["api"]["model"],
            "api_base_url": cfg["api"]["base_url"],
            "local_model": cfg["local"]["model"],
            "local_base_url": cfg["local"]["base_url"],
            "has_api_key": bool(cfg["api"]["api_key"])
        },
        "memories": memories(),
        "history": history()[-100:],
        "conversation": conversation(),
        "account": {"user_id": get_current_user(), "google_email": session.get("google_account_email") or google_info.get("email", "")},
        "conversations": list_conversations(20),
        "context": _ctx(),
        "task": _ctx().get("task", {}),
        "last_workspace": _ctx().get("last_workspace"),
        "tool_count": len(TOOL_DEFINITIONS),
        "google": {
            "credentials_file": google_ready,
            "token_file": bool(google_info.get("has_token")),
            "authorized": google_authorized,
            "needs_reauth": bool(google_info.get("needs_reauth")),
            "has_refresh_token": bool(google_info.get("has_refresh_token")),
            "expires_at": google_info.get("expires_at"),
            "missing_scopes": google_info.get("missing_scopes", []),
            "error": google_info.get("error", "")
        },
        "files": {"count": len(list_files()), "items": [public_item(x) for x in list_files()[:30]]},
        "memory_store": {**memory_stats(), "memory3": memory3_stats()},
        "google_backup": backup_status(),
        "workspace": {"available": google_authorized, "services": ["Drive", "Docs", "Sheets", "Slides", "Forms", "Tareas"]},
        "services": {
            "gmail": google_authorized and "https://www.googleapis.com/auth/gmail.readonly" not in google_info.get("missing_scopes", []),
            "calendar": google_authorized and "https://www.googleapis.com/auth/calendar" not in google_info.get("missing_scopes", []),
            "drive": google_authorized and "https://www.googleapis.com/auth/drive.readonly" not in google_info.get("missing_scopes", []),
            "docs": google_authorized and "https://www.googleapis.com/auth/documents" not in google_info.get("missing_scopes", []),
            "sheets": google_authorized and "https://www.googleapis.com/auth/spreadsheets" not in google_info.get("missing_scopes", []),
            "slides": google_authorized and "https://www.googleapis.com/auth/presentations" not in google_info.get("missing_scopes", []),
            "forms": google_authorized and "https://www.googleapis.com/auth/forms.body" not in google_info.get("missing_scopes", []),
            "contacts": google_authorized and "https://www.googleapis.com/auth/contacts" not in google_info.get("missing_scopes", []),
            "tasks": google_authorized and "https://www.googleapis.com/auth/tasks.readonly" not in google_info.get("missing_scopes", []),
        },
        "contacts": {"available": google_authorized},
        "maps": {"configured": bool(load().get("maps", {}).get("api_key")) or bool(__import__("os").environ.get("ZAR_MAPS_API_KEY"))},
        "gmail": {
            "credentials_file": google_ready,
            "token_file": google_authorized,
            "authorized": google_authorized,
            "needs_reauth": bool(google_info.get("needs_reauth"))
        }
    })

@app.get("/connect/google")
def connect_google():
    try:
        force = request.args.get("force", "0") == "1"
        if not force and connected():
            return "<script>window.close();</script><h2>Google ya está conectado</h2><p>Zar ha conservado tus credenciales. No necesitas volver a autorizarlo.</p>"
        session.pop("oauth_provider", None)
        session.pop("oauth_state", None)
        session.pop("oauth_code_verifier", None)
        # Use the exact host currently opened in the browser. This prevents
        # Railway alias mismatches. Persist the same URI with the transaction
        # so the code exchange uses exactly the URI used for authorization.
        redirect_uri = _google_redirect_uri()
        url, state, verifier = authorization_url(force=force, redirect_uri=redirect_uri)
        session["oauth_provider"] = "google"
        session["oauth_state"] = state
        session["oauth_code_verifier"] = verifier
        _save_oauth_pending('google', state, verifier, redirect_uri)
        return redirect(url)
    except Exception as exc:
        return f"<h2>No se pudo iniciar Google OAuth</h2><pre>{exc}</pre>", 500

@app.get("/connect/youtube")
def connect_youtube():
    canonical = _canonical_redirect_if_needed()
    if canonical:
        return canonical
    try:
        url, state, verifier = youtube_authorization_url(force=True)
        session["oauth_provider"] = "youtube"
        session["oauth_state"] = state
        session["oauth_code_verifier"] = verifier
        _save_oauth_pending('youtube', state, verifier)
        return redirect(url)
    except Exception as exc:
        return f"<h2>No se pudo iniciar la conexión de YouTube</h2><pre>{exc}</pre>", 500

@app.get("/api/tasks")
def tasks_endpoint():
    """Return the user's Google Tasks for the ZAR Tasks panel."""
    g = auth_status()
    if not g.get("connected"):
        return jsonify({"ok": False, "needs_google": True, "tasks": [], "error": "Google no está conectado."})
    missing = set(g.get("missing_scopes") or [])
    scope = "https://www.googleapis.com/auth/tasks.readonly"
    if scope in missing:
        return jsonify({"ok": False, "needs_google": True, "tasks": [], "error": "Google Tasks necesita autorización."})
    try:
        from .google_tasks import list_tasks
        rows = list_tasks(max_results=100, show_completed=True)
        pending = [r for r in rows if (r.get("task") or {}).get("status") != "completed"]
        completed = [r for r in rows if (r.get("task") or {}).get("status") == "completed"]
        return jsonify({
            "ok": True,
            "needs_google": False,
            "tasks": rows,
            "pending_count": len(pending),
            "completed_count": len(completed),
        })
    except Exception as exc:
        return jsonify({"ok": False, "needs_google": False, "tasks": [], "error": str(exc)}), 502


@app.get("/api/google/services/check")
def google_services_check():
    """Probe lightweight live Google APIs for the current user.

    Scope authorization and live API availability are reported separately so the
    UI never labels a service operational merely because its OAuth scope exists.
    """
    try:
        g = auth_status()
    except Exception as exc:
        return jsonify({"ok": False, "connected": False, "checked_at": datetime.now(timezone.utc).isoformat(), "services": [], "error": "No se pudo consultar la sesión de Google: " + str(exc)[:240]}), 502
    if not g.get("connected"):
        return jsonify({"ok": False, "connected": False, "checked_at": time.time(), "services": [], "error": "Google no está conectado."}), 401

    missing = set(g.get("missing_scopes") or [])
    specs = {
        "gmail": {"name":"Gmail", "icon":"📧", "scope":"https://www.googleapis.com/auth/gmail.readonly"},
        "calendar": {"name":"Calendar", "icon":"📅", "scope":"https://www.googleapis.com/auth/calendar"},
        "contacts": {"name":"Contactos", "icon":"👥", "scope":"https://www.googleapis.com/auth/contacts"},
        "tasks": {"name":"Tareas", "icon":"📋", "scope":"https://www.googleapis.com/auth/tasks.readonly"},
        "drive": {"name":"Drive", "icon":"☁️", "scope":"https://www.googleapis.com/auth/drive.readonly"},
        "docs": {"name":"Docs", "icon":"📝", "scope":"https://www.googleapis.com/auth/documents"},
        "sheets": {"name":"Sheets", "icon":"📊", "scope":"https://www.googleapis.com/auth/spreadsheets"},
        "slides": {"name":"Slides", "icon":"📽️", "scope":"https://www.googleapis.com/auth/presentations"},
        "forms": {"name":"Forms", "icon":"📋", "scope":"https://www.googleapis.com/auth/forms.body"},
    }
    rows=[]
    checked_at=datetime.now(timezone.utc).isoformat()
    try:
        creds=get_credentials(auto_refresh=True)
    except Exception as exc:
        return jsonify({"ok": False, "connected": False, "checked_at": checked_at, "services": [], "error": "No se pudieron cargar las credenciales de Google: " + str(exc)[:240]}), 502
    if not creds:
        return jsonify({"ok": False, "connected": False, "checked_at": checked_at, "services": [], "error": "No se pudieron cargar las credenciales de Google."}), 401

    def row(key, status, detail, latency_ms=None):
        base=specs[key].copy(); base.update({"key":key,"status":status,"detail":detail})
        if latency_ms is not None: base["latency_ms"]=latency_ms
        return base

    def probe(key, fn):
        if specs[key]["scope"] in missing:
            return row(key, "reauth", "Requiere autorización")
        started=time.perf_counter()
        try:
            fn()
            return row(key, "operational", "API operativa", round((time.perf_counter()-started)*1000))
        except Exception as exc:
            msg=str(exc).replace("\n", " ")[:220]
            return row(key, "error", msg or "La API devolvió un error", round((time.perf_counter()-started)*1000))

    def gmail():
        from googleapiclient.discovery import build
        build('gmail','v1',credentials=creds,cache_discovery=False).users().getProfile(userId='me').execute()
    def calendar():
        from googleapiclient.discovery import build
        build('calendar','v3',credentials=creds,cache_discovery=False).calendars().get(calendarId='primary').execute()
    def contacts():
        from googleapiclient.discovery import build
        build('people','v1',credentials=creds,cache_discovery=False).people().connections().list(resourceName='people/me',pageSize=1,personFields='names').execute()
    def tasks():
        from googleapiclient.discovery import build
        build('tasks','v1',credentials=creds,cache_discovery=False).tasklists().list(maxResults=1).execute()
    def drive():
        from googleapiclient.discovery import build
        build('drive','v3',credentials=creds,cache_discovery=False).about().get(fields='user(displayName,emailAddress),storageQuota').execute()
    # For Workspace editors there is no global "ping" endpoint. We use Drive to
    # locate at most one native object and, when available, ask the target API
    # for that object. With no matching object we still report the OAuth scope as
    # authorized instead of inventing a failed service state.
    def workspace_probe(kind, mime, getter):
        from googleapiclient.discovery import build
        d=build('drive','v3',credentials=creds,cache_discovery=False)
        files=d.files().list(q=f"mimeType='{mime}' and trashed=false",pageSize=1,fields='files(id)').execute().get('files',[])
        if not files:
            return
        getter(build(kind, credentials=creds, cache_discovery=False), files[0]['id'])
    def docs(): workspace_probe('docs','application/vnd.google-apps.document',lambda svc,fid: svc.documents().get(documentId=fid).execute())
    def sheets(): workspace_probe('sheets','application/vnd.google-apps.spreadsheet',lambda svc,fid: svc.spreadsheets().get(spreadsheetId=fid,fields='spreadsheetId').execute())
    def slides(): workspace_probe('slides','application/vnd.google-apps.presentation',lambda svc,fid: svc.presentations().get(presentationId=fid).execute())
    def forms(): workspace_probe('forms','application/vnd.google-apps.form',lambda svc,fid: svc.forms().get(formId=fid).execute())

    for key, fn in (("gmail",gmail),("calendar",calendar),("contacts",contacts),("tasks",tasks),("drive",drive),("docs",docs),("sheets",sheets),("slides",slides),("forms",forms)):
        r=probe(key,fn)
        # If a Workspace API had no native object, the call above still proved
        # the credential can reach Drive. Keep the service as authorized, but say
        # explicitly that there was no object available for a deeper API probe.
        if r["status"]=="operational" and key in {"docs","sheets","slides","forms"}:
            r["detail"]="API autorizada; comprobación profunda disponible al encontrar un documento/hoja/presentación/formulario"
        rows.append(r)

    account=g.get('email','')
    return jsonify({"ok":True,"connected":True,"account":account,"has_refresh_token":bool(creds.refresh_token),"checked_at":checked_at,"services":rows})

@app.get("/api/control/health")
def control_health():
    """Return a compact, UI-safe health summary for Zar's control center."""
    cfg = load()
    g = auth_status()
    services = {
        "gmail": ("Gmail", "📧", "gmail.readonly"),
        "calendar": ("Calendario", "📅", "calendar"),
        "contacts": ("Contactos", "👥", "contacts"),
        "tasks": ("Tareas", "📋", "tasks.readonly"),
        "drive": ("Drive", "☁️", "drive.readonly"),
        "docs": ("Docs", "📝", "documents"),
        "sheets": ("Sheets", "📊", "spreadsheets"),
        "slides": ("Slides", "📽️", "presentations"),
        "forms": ("Forms", "📋", "forms.body"),
    }
    scopes = {
        "gmail": "https://www.googleapis.com/auth/gmail.readonly",
        "calendar": "https://www.googleapis.com/auth/calendar",
        "contacts": "https://www.googleapis.com/auth/contacts",
        "tasks": "https://www.googleapis.com/auth/tasks.readonly",
        "drive": "https://www.googleapis.com/auth/drive.readonly",
        "docs": "https://www.googleapis.com/auth/documents",
        "sheets": "https://www.googleapis.com/auth/spreadsheets",
        "slides": "https://www.googleapis.com/auth/presentations",
        "forms": "https://www.googleapis.com/auth/forms.body",
    }
    missing = set(g.get("missing_scopes") or [])
    service_rows = []
    for key, (name, icon, _) in services.items():
        scope = scopes[key]
        if not g.get("connected"):
            status, label = "disconnected", "No conectado"
        elif scope in missing:
            status, label = "reauth", "Requiere autorización"
        else:
            status, label = "connected", "Autorizado"
        service_rows.append({"key": key, "name": name, "icon": icon, "status": status, "label": label})

    account = None
    if g.get("connected"):
        try:
            creds = get_credentials()
            if creds:
                from googleapiclient.discovery import build
                profile = build("gmail", "v1", credentials=creds, cache_discovery=False).users().getProfile(userId="me").execute()
                account = profile.get("emailAddress")
        except Exception:
            account = None

    bs = backup_status() or {}
    bstats = bs.get("stats") or {}
    backup_state = "not_started"
    if bs.get("status") == "running": backup_state = "running"
    elif bs.get("status") == "done": backup_state = "done"
    elif bs.get("status") == "error": backup_state = "error"

    authorized_count = sum(1 for x in service_rows if x["status"] == "connected")
    try:
        from .model_router import catalog as model_catalog
    except ImportError:
        from model_router import catalog as model_catalog
    api_cfg = cfg.get("api") or {}
    local_cfg = cfg.get("local") or {}
    return jsonify({
        "ok": True,
        "version": "30.2.0",
        "google": {**g, "account": account},
        "services": service_rows,
        "service_count": len(service_rows),
        "authorized_count": authorized_count,
        "google_state": "connected" if g.get("connected") and not g.get("missing_scopes") else ("reauth" if g.get("connected") else "disconnected"),
        "backup": {
            "state": backup_state,
            "started_at": bs.get("started_at"),
            "finished_at": bs.get("finished_at"),
            "path": bs.get("path"),
            "error": bs.get("error"),
            "stats": bstats,
        },
        "memory": {**memory_stats(), "memory3": memory3_stats(), "insights": memory_insights()},
        "maps": {"configured": bool(cfg.get("maps", {}).get("api_key")) or bool(os.environ.get("ZAR_MAPS_API_KEY"))},
        "ai": {
            "provider": cfg.get("provider"),
            "model": api_cfg.get("model") if cfg.get("provider") == "api" else local_cfg.get("model"),
            "api_configured": bool(api_cfg.get("api_key") or os.environ.get("GEMINI_API_KEY")),
            "local_configured": bool(local_cfg.get("model")),
            "models": model_catalog(),
        },
        "storage": {"data_dir": os.environ.get("ZAR_DATA_DIR", "/data"), "persistent_hint": os.path.exists(os.environ.get("ZAR_DATA_DIR", "/data"))},
    })

@app.get("/api/google/backup/status")
def google_backup_status():
    return jsonify(backup_status())

@app.post("/api/google/backup/start")
def google_backup_start():
    try:
        if not auth_status().get("connected"):
            return jsonify({"ok": False, "error": "Google no está conectado."}), 401
        return jsonify({"ok": True, **start_google_backup("manual")})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

@app.get("/api/youtube/status")
def api_youtube_status():
    return jsonify(youtube_status())

@app.get("/connect/gmail")
def connect_gmail():
    # Gmail and Calendar share the same Google OAuth token in Zar Cloud.
    try:
        force = request.args.get("force", "0") == "1"
        if not force and connected():
            return "<script>window.close();</script><h2>Google ya está conectado</h2><p>Gmail y Calendar ya tienen una sesión persistente en Zar.</p>"
        redirect_uri = _google_redirect_uri()
        url, state, verifier = authorization_url(force=force, redirect_uri=redirect_uri)
        session["oauth_state"] = state
        session["oauth_code_verifier"] = verifier
        _save_oauth_pending('google', state, verifier, redirect_uri)
        return redirect(url)
    except Exception as exc:
        return f"<h2>No se pudo iniciar Google OAuth</h2><pre>{exc}</pre>", 500

@app.get("/api/connections")
def connections():
    google_ready = True
    google_authorized = connected()
    return jsonify({
        "google_calendar": {
            "credentials": google_ready,
            "authorized": google_authorized
        },
        "files": {"count": len(list_files()), "items": [public_item(x) for x in list_files()[:30]]},
        "workspace": {"available": google_authorized, "services": ["Drive", "Docs", "Sheets", "Slides", "Forms"]},
        "services": {
            "gmail": google_authorized and "https://www.googleapis.com/auth/gmail.readonly" not in google_info.get("missing_scopes", []),
            "calendar": google_authorized and "https://www.googleapis.com/auth/calendar" not in google_info.get("missing_scopes", []),
            "drive": google_authorized and "https://www.googleapis.com/auth/drive.readonly" not in google_info.get("missing_scopes", []),
            "docs": google_authorized and "https://www.googleapis.com/auth/documents" not in google_info.get("missing_scopes", []),
            "sheets": google_authorized and "https://www.googleapis.com/auth/spreadsheets" not in google_info.get("missing_scopes", []),
            "slides": google_authorized and "https://www.googleapis.com/auth/presentations" not in google_info.get("missing_scopes", []),
            "forms": google_authorized and "https://www.googleapis.com/auth/forms.body" not in google_info.get("missing_scopes", []),
            "contacts": google_authorized and "https://www.googleapis.com/auth/contacts" not in google_info.get("missing_scopes", []),
        },
        "contacts": {"available": google_authorized},
        "maps": {"configured": bool(load().get("maps", {}).get("api_key")) or bool(__import__("os").environ.get("ZAR_MAPS_API_KEY"))},
        "gmail": {
            "credentials": google_ready,
            "authorized": google_authorized
        }
    })

@app.get("/api/ollama")
def ollama_status():
    cfg = load()
    base = cfg.get("local",{}).get("base_url","http://127.0.0.1:11434").rstrip("/")
    model = cfg.get("local",{}).get("model","qwen3:8b")
    try:
        r = requests.get(base + "/api/tags", timeout=5)
        if not r.ok:
            return jsonify({"ok":False,"error":f"Ollama respondió HTTP {r.status_code}"}), 200
        data = r.json()
        names=[m.get("name","") for m in data.get("models",[])]
        exact = model in names
        return jsonify({"ok":True,"running":True,"model":model,"installed":exact,"models":names})
    except Exception as exc:
        return jsonify({"ok":False,"running":False,"model":model,"installed":False,"error":str(exc)}), 200

@app.get("/api/contacts")
def contacts_api():
    try:
        q = (request.args.get("q") or "").strip()
        try:
            from .google_contacts import search_contacts
        except ImportError:
            from google_contacts import search_contacts
        return jsonify({"ok": True, "contacts": search_contacts(q, 20)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "contacts": []}), 200

@app.get("/api/web/search")
def web_search_api():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"ok": False, "error": "Falta la consulta."}), 400
    try:
        try:
            from .web_search import google_web_search
        except ImportError:
            from web_search import google_web_search
        return jsonify(google_web_search(q))
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 200

@app.post("/api/research/start")
def research_start_api():
    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"ok": False, "error": "Falta la consulta de investigación."}), 400
    try:
        started = start_research(query, data.get("instructions") or "")
        return jsonify({"ok": True, **started}), 202
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 200

@app.get("/api/research/<interaction_id>")
def research_status_api(interaction_id):
    try:
        data = get_research(interaction_id)
        return jsonify({
            "ok": True,
            "id": interaction_id,
            "status": data.get("status"),
            "report": extract_report(data),
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 200

@app.get("/api/research/archive")
def research_archive_api():
    try:
        return jsonify({"ok": True, "reports": list_reports(int(request.args.get("limit", 30)))})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "reports": []}), 200

@app.get("/api/research/archive/<report_id>")
def research_archive_item_api(report_id):
    try:
        item = get_report(report_id)
        if not item:
            return jsonify({"ok": False, "error": "Investigación no encontrada."}), 404
        return jsonify({"ok": True, **item})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 200

@app.get("/api/online")
def online_status():
    cfg = load()
    active = cfg.get("provider", "gemini")
    profile = cfg.get("openrouter", {}) if active == "openrouter" else cfg.get("api", {})
    return jsonify({"provider": active, "configured": bool(profile.get("api_key")), "model": profile.get("model", "")})

@app.post("/api/config")
def update_config():
    data = request.get_json(silent=True) or {}
    cfg = load()
    if data.get("provider") in ("api","local"):
        cfg["provider"] = data["provider"]
    if isinstance(data.get("api"), dict):
        cfg["api"].update({k:v for k,v in data["api"].items() if k in ("base_url","api_key","model")})
    if isinstance(data.get("local"), dict):
        cfg["local"].update({k:v for k,v in data["local"].items() if k in ("base_url","model")})
    save(cfg)
    return jsonify({"ok":True})

@app.post("/api/test")
def test():
    try:
        reply = respond("Di únicamente: conexión correcta.")
        return jsonify({"ok":True,"reply":reply})
    except Exception as exc:
        return jsonify({"ok":False,"reply":str(exc)})

def _execute_workspace_action(pending):
    service = pending.get("service")
    action = pending.get("action")
    args = pending.get("args") or {}
    try:
        from . import google_workspace as gw
    except ImportError:
        import google_workspace as gw
    if service == "Google Docs":
        return gw.docs_create(args["title"], args.get("text", "")) if action == "crear documento" else gw.docs_append(args["document_id"], args["text"])
    if service == "Google Sheets":
        return gw.sheets_create(args["title"]) if action == "crear hoja de cálculo" else gw.sheets_write(args["spreadsheet_id"], args["range_a1"], args["values"])
    if service == "Google Slides":
        return gw.slides_create(args["title"])
    if service == "Google Forms":
        if action == "crear formulario":
            return gw.forms_create(args["title"], args.get("description", ""))
        if action == "añadir pregunta":
            return gw.forms_add_question(args["form_id"], args["question"], args.get("required", False), args.get("paragraph", False))
    raise RuntimeError("Acción de Google Workspace no reconocida.")


def _process_chat_message(msg):
    low = (msg or "").strip().lower()
    ctx = _ctx()
    pending_email = ctx.get("pending_email")
    LAST_EMAIL = ctx.get("active_email")
    pending_contact = ctx.get("pending_contact")
    if pending_contact and _looks_like_send(msg):
        try:
            result = _execute_contact_action(pending_contact)
            from .context import clear_pending_contact
            clear_pending_contact()
            set_last_contact(result)
            set_task_state("google contacts", "contact", result.get("resourceName", ""), pending_contact.get("action", ""), "high", "completed", f"Acción realizada en Google Contacts")
            reply = f"✅ He realizado la acción en Google Contacts.\n\nContacto: {result.get('name') or '(sin nombre)'}"
            if result.get("email"):
                reply += f"\nEmail: {result.get('email')}"
            if result.get("phone"):
                reply += f"\nTeléfono: {result.get('phone')}"
            _remember_turn("user", msg); _remember_turn("assistant", reply); return reply
        except Exception as exc:
            clear_pending_contact()
            reply = f"No he podido modificar el contacto: {exc}"
            _remember_turn("user", msg); _remember_turn("assistant", reply); return reply
    if pending_contact and _looks_like_cancel(msg):
        from .context import clear_pending_contact
        clear_pending_contact()
        clear_task_state()
        reply = "🟢 No he modificado el contacto."
        _remember_turn("user", msg); _remember_turn("assistant", reply); return reply
    pending_workspace = ctx.get("pending_workspace")

    if pending_workspace and _looks_like_send(msg):
        try:
            result = _execute_workspace_action(pending_workspace)
            clear_pending_workspace()
            try:
                from .context import set_last_workspace
            except ImportError:
                from context import set_last_workspace
            workspace_obj = dict(result or {})
            workspace_obj.update({"service": pending_workspace.get("service"), "action": pending_workspace.get("action"), "requested_args": pending_workspace.get("args") or {}})
            set_last_workspace(workspace_obj)
            set_task_state("google workspace", (pending_workspace.get("service") or "workspace").lower(), result.get("id", result.get("documentId", result.get("spreadsheetId", result.get("presentationId", result.get("formId", ""))))), pending_workspace.get("action", ""), "high", "completed", f"Acción realizada en {pending_workspace.get('service')}")
            url = result.get("url") or result.get("htmlLink") or ""
            reply = f"✅ He realizado la acción en {pending_workspace.get('service')}." + (f"\n{url}" if url else "")
        except Exception as exc:
            reply = f"No he podido realizar la acción en Google Workspace: {exc}"
        _remember_turn("user",msg); _remember_turn("assistant",reply)
        return reply

    if pending_workspace and _looks_like_cancel(msg):
        clear_pending_workspace()
        reply = "✅ He cancelado la acción pendiente de Google Workspace."
        _remember_turn("user",msg); _remember_turn("assistant",reply)
        return reply


    # Contexto natural: permite usar «guárdala», «hazlo más formal», «contéstale que…»
    # y preguntas cortas sobre el correo actual sin repetir el objeto de la conversación.

    # Confirmación de envío. Las direcciones noreply requieren una confirmación más explícita.
    if _looks_like_send(msg):
        if pending_email:
            if pending_email.get("noreply") or _is_noreply(pending_email.get("to", "")):
                reply = ("⚠️ No lo he enviado. El destinatario parece una dirección automática (noreply) "
                         "y es posible que no acepte respuestas. Si realmente quieres intentarlo, escribe «enviar de todos modos»." )
            else:
                try:
                    from .gmail import send_message
                    sent = send_message(
                        pending_email["to"], pending_email["subject"], pending_email["body"],
                        pending_email.get("reply_to_message_id") or None,
                        pending_email.get("thread_id") or None
                    )
                    clear_pending(keep_email=True)
                    set_task_state("responder correo", "email", "", "enviar", "irreversible", "sent", "Correo enviado correctamente")
                    reply = "✅ Correo enviado correctamente." if sent.get("id") else "No he podido confirmar el envío."
                except Exception as exc:
                    reply = f"No he podido enviar el correo: {exc}"
            _remember_turn("user",msg); _remember_turn("assistant",reply)
            return reply

    if low in ("enviar de todos modos", "envíalo de todos modos", "envialo de todos modos", "sí, envía de todos modos", "si, envia de todos modos"):
        if pending_email:
            try:
                from .gmail import send_message
                sent = send_message(
                    pending_email["to"], pending_email["subject"], pending_email["body"],
                    pending_email.get("reply_to_message_id") or None,
                    pending_email.get("thread_id") or None
                )
                clear_pending(keep_email=True)
                set_task_state("responder correo", "email", "", "enviar", "irreversible", "sent", "Correo enviado tras confirmación explícita")
                reply = "✅ He enviado el correo porque me has confirmado expresamente que lo haga de todos modos." if sent.get("id") else "No he podido confirmar el envío."
            except Exception as exc:
                reply = f"No he podido enviar el correo: {exc}"
            _remember_turn("user",msg); _remember_turn("assistant",reply)
            return reply

    if pending_email and _looks_like_save_draft(msg):
        try:
            from .gmail import create_draft, update_draft
            existing_id = _ctx().get("saved_draft_id", "")
            if existing_id:
                saved = update_draft(existing_id, pending_email["to"], pending_email["subject"], pending_email["body"], pending_email.get("reply_to_message_id") or None, pending_email.get("thread_id") or None)
                draft_id = saved.get("id", existing_id)
            else:
                saved = create_draft(
                    pending_email["to"], pending_email["subject"], pending_email["body"],
                    pending_email.get("reply_to_message_id") or None,
                    pending_email.get("thread_id") or None
                )
                draft_id = saved.get("id", "")
            mark_saved_draft(draft_id)
            set_focus("email_draft", pending_email.get("subject") or "borrador actual")
            set_task_state("responder correo", "email_draft", draft_id, "guardar", "low", "draft_saved", pending_email.get("subject") or "borrador guardado")
            reply = f"✅ He guardado el correo como borrador en Gmail. No se ha enviado." + (f"\nID del borrador: {draft_id}" if draft_id else "")
        except Exception as exc:
            err = str(exc)
            if "insufficient authentication scopes" in err.lower() or "insufficientpermissions" in err.lower():
                reply = (
                    "⚠️ Gmail está conectado con permisos antiguos que permiten leer/enviar, pero no crear borradores.\n\n"
                    "He preparado el borrador, pero para guardarlo en Gmail necesito que vuelvas a autorizar Zar. "
                    "Cierra esta ventana, elimina el archivo gmail_token.json de la carpeta de Zar y pulsa «Conectar Gmail» otra vez. "
                    "Google te pedirá permiso para gestionar borradores. No necesitas reinstalar Ollama."
                )
            else:
                reply = f"No he podido guardar el borrador en Gmail: {exc}"
        _remember_turn("user",msg); _remember_turn("assistant",reply)
        return reply

    if pending_email and _looks_like_draft_edit(msg):
        try:
            revised = revise_email_draft(LAST_EMAIL, pending_email.get("body", ""), msg) if LAST_EMAIL else None
            if not revised:
                reply = "No tengo el correo original en contexto para revisar este borrador."
            else:
                revised_pending = _pending_email_from(revised)
                saved_id = _ctx().get("saved_draft_id", "")
                if saved_id:
                    try:
                        from .gmail import update_draft
                        update_draft(saved_id, revised_pending["to"], revised_pending["subject"], revised_pending["body"], revised_pending.get("reply_to_message_id") or None, revised_pending.get("thread_id") or None)
                    except Exception as exc:
                        # Keep local cloud context even if Gmail cannot update the existing draft.
                        saved_id = ""
                _set_pending(revised_pending)
                set_focus("email_draft", revised_pending.get("subject") or "borrador actual")
                if saved_id:
                    mark_saved_draft(saved_id)
                reply = _email_card(revised, question=True)
        except Exception as exc:
            reply = f"No he podido modificar el borrador: {exc}"
        _remember_turn("user",msg); _remember_turn("assistant",reply)
        return reply

    if _looks_like_cancel(msg):
        if clear_pending(keep_email=True):
            reply = "Cancelado. No he enviado el correo."
            _remember_turn("user",msg); _remember_turn("assistant",reply)
            return reply

    # V17: el agente semántico es ahora la ruta principal para TODO el lenguaje natural.
    # Las acciones de seguridad (enviar/cancelar/guardar) se resuelven antes para
    # mantener controles explícitos. El resto pasa por el modelo para interpretar
    # intención, referencias y herramientas, tanto en Gmail como en Calendar y
    # futuras integraciones.
    semantic_candidate = not _looks_like_cancel(msg)
    if semantic_candidate:
        _remember_turn("user", msg)
        try:
            # En la capa semántica saltamos el enrutador de frases exactas y
            # hablamos directamente con el agente IA. Así el propio modelo
            # interpreta la intención y decide qué herramientas necesita,
            # evitando devolver marcadores internos como DIRECT_GMAIL::.
            from .agent import semantic_respond
            semantic_reply = semantic_respond(msg)
            if semantic_reply and not (isinstance(semantic_reply, str) and semantic_reply.startswith("Error de Zar:")):
                reply = semantic_reply
                if isinstance(reply, str) and reply.startswith("HE_EMAIL::"):
                    import json as _json
                    draft = _json.loads(reply.split("::",1)[1])
                    _set_pending(_pending_email_from(draft)); set_focus("email_draft", draft.get("subject") or "borrador actual")
                    reply = _email_card(draft, question=True)
                elif isinstance(reply, str) and reply.startswith("WORKSPACE_ACTION::"):
                    # El agente semántico ha elegido una acción de Google Workspace.
                    # Nunca mostramos el marcador interno al usuario: convertimos la
                    # acción en una operación pendiente y pedimos confirmación explícita.
                    import json as _json
                    data = _json.loads(reply.split("::", 1)[1])
                    pending = {
                        "service": data.get("service", "Google Workspace"),
                        "action": data.get("action", "realizar una acción"),
                        "args": data.get("args") or {},
                    }
                    set_pending_workspace(pending)
                    set_task_state(
                        "google workspace",
                        (pending.get("service") or "workspace").lower(),
                        "",
                        pending.get("action", ""),
                        "high",
                        "awaiting_confirmation",
                        f"Preparado para {pending.get('action','acción')} en {pending.get('service','Google Workspace')}"
                    )
                    reply = (
                        f"⚠️ Voy a {pending.get('action','realizar esta acción')} en "
                        f"{pending.get('service','Google Workspace')}.\n\n"
                        "¿Confirmas? Responde «sí» para continuar o «cancelar» para detenerlo."
                    )
                _remember_turn("assistant", reply)
                return reply
        except Exception:
            pass
        # Evita duplicar el turno si hacemos fallback a la lógica clásica.
        try:
            history_now = conversation()
            if history_now and history_now[-1].get("role") == "user" and history_now[-1].get("content") == msg:
                history_now.pop()
        except Exception:
            pass

    # Resolver primero referencias de correo que dependen del contexto persistente.
    contextual = _contextual_gmail_intent(msg, ctx, pending_email, LAST_EMAIL)
    if contextual == "summarize":
        try:
            summary = summarize_email(LAST_EMAIL) if LAST_EMAIL else "No tengo un correo abierto todavía."
            if LAST_EMAIL:
                set_summary(summary)
                set_focus("email", LAST_EMAIL.get("subject") or "correo actual")
                reply = "📝 Resumen del correo:\n\n" + summary
            else:
                reply = "No tengo un correo abierto todavía. Dime «mira mi último correo»."
        except Exception as exc:
            reply = f"No he podido resumir el correo: {exc}"
        _remember_turn("user",msg); _remember_turn("assistant",reply)
        return reply
    if isinstance(contextual, dict) and contextual.get("type") == "draft_context":
        try:
            if not LAST_EMAIL:
                reply = "No tengo un correo abierto todavía. Dime «mira mi último correo»."
            else:
                draft = draft_reply_email(LAST_EMAIL, contextual.get("instruction", ""))
                _set_pending(_pending_email_from(draft))
                set_focus("email_draft", draft.get("subject") or "borrador actual")
                set_task_state("responder correo", "email_draft", draft.get("reply_to_message_id", "") or draft.get("thread_id", ""), "preparar", "low", "draft_ready", draft.get("subject") or "borrador actual")
                reply = _email_card(draft, question=True)
        except Exception as exc:
            reply = f"No he podido preparar la respuesta: {exc}"
        _remember_turn("user",msg); _remember_turn("assistant",reply)
        return reply

    _remember_turn("user",msg)

    try:
        reply = respond(msg)
        if isinstance(reply, str) and reply.startswith("DEEP_RESEARCH::"):
            try:
                spec = json.loads(reply.split("::", 1)[1])
                query = (spec.get("query") or msg).strip()
                started = start_research(query)
                interaction_id = started.get("id")
                finished, report = wait_for_research(interaction_id, poll_seconds=5, max_seconds=3300)
                saved = save_report(query, report, interaction_id, started.get("model"))
                reply = (
                    "🔎 **Investigación completada**\n\n"
                    + report.strip()
                    + "\n\n---\n"
                    + f"🗂️ Investigación guardada en ZAR · ID: `{saved['id']}`"
                )
            except Exception as exc:
                reply = f"⚠️ No he podido completar la investigación profunda: {exc}"
        if isinstance(reply, str) and reply.startswith("DIRECT_WORKSPACE::"):
            data = json.loads(reply.split("::", 1)[1])
            typ = data.get("type")
            try:
                from . import google_workspace as gw
            except ImportError:
                import google_workspace as gw
            if typ == "drive_search":
                found = gw.drive_search(data.get("name", ""), data.get("max_results", 20))
                if found:
                    lines = [f"• {x.get('name','(sin nombre)')} — {x.get('mimeType','')}" + (f" — {x.get('webViewLink')}" if x.get('webViewLink') else "") for x in found]
                    reply = "☁️ He buscado en Google Drive:\n\n" + "\n".join(lines)
                else:
                    reply = f"No he encontrado ningún archivo llamado «{data.get('name','')}» en Google Drive accesible para Zar."
            elif typ == "drive_list":
                found = gw.drive_list(None, data.get("max_results", 20))
                if found:
                    lines = [f"• {x.get('name','(sin nombre)')} — {x.get('mimeType','')}" + (f" — {x.get('webViewLink')}" if x.get('webViewLink') else "") for x in found]
                    reply = "☁️ Estos son tus archivos recientes de Google Drive accesibles para Zar:\n\n" + "\n".join(lines)
                else:
                    reply = "No he encontrado archivos de Google Drive accesibles para Zar con la autorización actual."
            else:
                mapping = {
                    "docs_create": ("Google Docs", "crear documento"),
                    "docs_append": ("Google Docs", "añadir texto al documento"),
                    "sheets_create": ("Google Sheets", "crear hoja de cálculo"),
                    "sheets_write": ("Google Sheets", "escribir datos"),
                    "slides_create": ("Google Slides", "crear presentación"),
                    "forms_create": ("Google Forms", "crear formulario"),
                }
                if typ in mapping:
                    service, action = mapping[typ]
                    args = dict(data)
                    args.pop("type", None)
                    pending = {"service": service, "action": action, "args": args}
                    set_pending_workspace(pending)
                    set_task_state("google workspace", service.lower(), "", action, "high", "awaiting_confirmation", f"Preparado para {action} en {service}")
                    reply = f"⚠️ Voy a {action} en {service}.\n\n¿Confirmas? Responde «sí» para continuar o «cancelar» para detenerlo."
        if isinstance(reply, str) and reply.startswith("CONTACT_EMAIL_MISSING::"):
            try:
                data = json.loads(reply.split("::", 1)[1])
                contact = data.get("contact") or {}
                name = contact.get("name") or "Ese contacto"
                reply = f"No puedo preparar el correo todavía: {name} no tiene ningún email guardado en tus contactos. Dime qué dirección quieres usar para continuar."
            except Exception:
                reply = "No puedo preparar el correo porque el contacto seleccionado no tiene un email guardado. Dime qué dirección quieres usar para continuar."

        if isinstance(reply, str) and reply.startswith("CONTACT_ACTION::"):
            try:
                data = json.loads(reply.split("::", 1)[1])
                pending = {k: data.get(k) for k in ("action", "args")}
                from .context import set_pending_contact
                set_pending_contact(pending)
                set_task_state("google contacts", "contact", (pending.get("args") or {}).get("resource_name", ""), pending.get("action", ""), "high", "awaiting_confirmation", f"Preparado para {pending.get('action','acción')} en Google Contacts")
                args = pending.get("args") or {}
                if pending.get("action") == "crear contacto":
                    detail = f"\n\nNombre: {args.get('name','')}"
                    if args.get('email'):
                        detail += f"\nEmail: {args.get('email')}"
                    if args.get('phone'):
                        detail += f"\nTeléfono: {args.get('phone')}"
                    if args.get('company'):
                        detail += f"\nEmpresa: {args.get('company')}"
                else:
                    detail = ""
                reply = (
                    f"⚠️ Voy a {pending.get('action','realizar esta acción')} en Google Contacts.{detail}"
                    "\n¿Confirmas? Responde «sí» para continuar o «cancelar» para detenerlo."
                )
            except Exception as exc:
                reply = f"No he podido preparar la acción de Google Contacts: {exc}"
        if isinstance(reply, str) and reply.startswith("WORKSPACE_ACTION::"):
            try:
                data = json.loads(reply.split("::", 1)[1])
                pending = {k: data.get(k) for k in ("service", "action", "args")}
                set_pending_workspace(pending)
                set_task_state("google workspace", (data.get("service") or "workspace").lower(), "", data.get("action", ""), "high", "awaiting_confirmation", f"Preparado para {data.get('action','acción')} en {data.get('service','Google Workspace')}")
                reply = f"⚠️ Voy a {data.get('action','realizar esta acción')} en {data.get('service','Google Workspace')}.\n\n¿Confirmas? Responde «sí» para continuar o «cancelar» para detenerlo."
            except Exception as exc:
                reply = f"No he podido preparar la acción de Google Workspace: {exc}"
    except Exception as exc:
        reply = f"Error de Zar: {exc}"

    if isinstance(reply,str) and reply.startswith("DIRECT_GMAIL_COMPOUND::"):
        try:
            import json as _json
            from .gmail import get_latest
            intent = _json.loads(reply.split("::",1)[1])
            msg_data = get_latest()
            if not msg_data:
                reply = "No he encontrado ningún correo en la bandeja de entrada."
            else:
                _set_email(msg_data)
                set_focus("email", msg_data.get("subject") or "correo actual")
                set_task_state("entender correo", "email", msg_data.get("id", ""), "analizar", "low", "email_active", msg_data.get("subject") or "correo actual")
                # Mantener también la variable local sincronizada con el contexto
                # persistente para que la misma petición pueda encadenar
                # lectura -> resumen -> redacción sin usar None.
                LAST_EMAIL = msg_data
                # Primero explicamos de qué trata/qué necesita el correo.
                summary = summarize_email(msg_data)
                set_summary(summary)
                # Después redactamos solo la acción solicitada por el usuario.
                draft = draft_reply_email(msg_data, intent.get("instruction", ""))
                _set_pending(_pending_email_from(draft))
                set_focus("email_draft", draft.get("subject") or "borrador actual")
                reply = (
                    "📧 He mirado tu último correo.\n\n"
                    "📝 Qué quiere / qué dice:\n" + summary.strip() + "\n\n"
                    + _email_card(draft, question=True)
                )
        except Exception as exc:
            reply = f"No he podido completar la petición sobre el correo: {exc}"

    elif isinstance(reply,str) and reply.startswith("DIRECT_GMAIL_DRAFT_CONTEXT::"):
        try:
            from .gmail import get_latest
            if not LAST_EMAIL:
                _set_email(get_latest())
            if not LAST_EMAIL:
                reply = "No tengo ningún correo abierto todavía. Dime «abre mi último correo»."
            else:
                draft = draft_reply_email(LAST_EMAIL, msg)
                _set_pending(_pending_email_from(draft))
                reply = _email_card(draft, question=True)
        except Exception as exc:
            reply = f"No he podido redactar la respuesta: {exc}"

    elif isinstance(reply,str) and reply.startswith("DIRECT_GMAIL_LATEST::"):
        try:
            from .gmail import get_latest
            msg_data = get_latest()
            if not msg_data:
                reply = "No he encontrado ningún correo en la bandeja de entrada."
            else:
                _set_email(msg_data)
                reply = (
                    f"📧 He abierto tu último correo.\n\n"
                    f"De: {msg_data.get('from','')}\n"
                    f"Asunto: {msg_data.get('subject') or '(sin asunto)'}\n"
                    f"Fecha: {msg_data.get('date','')}\n\n"
                    f"{msg_data.get('text','')[:14000]}\n\n"
                    "Puedes decirme «resúmelo» para que te haga un resumen."
                )
        except Exception as exc:
            reply = f"No he podido abrir el último correo: {exc}"

    elif isinstance(reply,str) and reply.startswith("DIRECT_GMAIL_SUMMARIZE::"):
        if LAST_EMAIL:
            try:
                reply = "📝 Resumen del correo:\n\n" + summarize_email(LAST_EMAIL)
            except Exception as exc:
                reply = f"No he podido resumir el correo: {exc}"
        else:
            reply = "Todavía no tengo ningún correo abierto. Dime «abre mi último correo»."

    elif isinstance(reply,str) and reply.startswith("DIRECT_GMAIL::"):
        import json as _json
        try:
            intent = _json.loads(reply.split("::",1)[1])
            result = execute_tool("gmail_search", {
                "query": intent.get("query","in:inbox"),
                "max_results": intent.get("max_results",10)
            })
            msgs = result.get("messages",[]) if result.get("ok") else []
            if not msgs:
                reply = "No he encontrado correos que coincidan con esa petición."
            elif intent.get("type") == "from":
                from .gmail import get_message
                opened = get_message(msgs[0]["id"])
                _set_email(opened)
                reply = (
                    f"📧 He abierto el correo encontrado.\n\n"
                    f"De: {opened.get('from','')}\n"
                    f"Asunto: {opened.get('subject') or '(sin asunto)'}\n"
                    f"Fecha: {opened.get('date','')}\n\n"
                    f"{opened.get('text','')[:14000]}\n\n"
                    "Puedes decirme «resúmelo»."
                )
            else:
                lines = ["Estos son los correos que he encontrado:"]
                for m in msgs:
                    state = " [NO LEÍDO]" if m.get("unread") else ""
                    lines.append(f"• {m.get('subject') or '(sin asunto)'}{state}\n  De: {m.get('from','')}\n  {m.get('date','')}\n  {m.get('snippet','')}")
                reply = "\n".join(lines)
        except Exception as exc:
            reply = f"No he podido consultar Gmail: {exc}"

    if isinstance(reply,str) and reply.startswith("DIRECT_MEDIA::"):
        import json as _json
        try:
            media = _json.loads(reply.split("::",1)[1])
            platform = media.get("platform")
            query = (media.get("query") or "").strip()
            if not query:
                if platform == "youtube":
                    reply = "¿Qué quieres buscar en YouTube?"
                else:
                    reply = "¿Qué quieres buscar en Spotify?"
            else:
                from urllib.parse import quote as _quote
                if platform == "youtube":
                    url = f"https://www.youtube.com/results?search_query={_quote(query)}"
                    label = "YouTube"
                else:
                    url = f"https://open.spotify.com/search/{_quote(query)}"
                    label = "Spotify"
                set_focus(platform, query)
                set_media(platform, query, url)
                set_task_state(f"buscar en {label}", platform, "", "buscar", "low", "completed", f"Búsqueda preparada: {query}")
                reply = f"🎵 He preparado la búsqueda en {label}: {query}\n\n{url}"
        except Exception as exc:
            reply = f"No he podido preparar la búsqueda multimedia: {exc}"

    if isinstance(reply,str) and reply.startswith("LOCAL_REMINDER::"):
        import json as _json
        try:
            draft = _json.loads(reply.split("::",1)[1])
            missing = draft.get("needs_clarification",[])
            if missing:
                prompts=[]
                if "fecha" in missing: prompts.append("qué día")
                if "hora" in missing: prompts.append("a qué hora")
                if "título" in missing: prompts.append("qué nombre o motivo")
                reply="Claro. Para crear el recordatorio necesito saber " + " y ".join(prompts) + "."
                set_pending_calendar({"partial": draft})
            else:
                set_pending_calendar({"event": {"summary":draft["summary"],"start_iso":draft["start_iso"],"end_iso":draft["end_iso"]}})
                reply=(f"📅 He preparado este recordatorio:\n\n«{draft['summary']}»\n"
                       f"{draft['date_human']} · {draft['time_human']}\n\n"
                       "¿Quieres que lo cree en Google Calendar?\n\n"
                       "Escribe «sí» para confirmar o «cancelar».")
        except Exception as exc:
            reply=f"No he podido preparar el recordatorio: {exc}"

    if isinstance(reply,str) and reply.startswith("DIRECT_CALENDAR_QUERY::"):
        try:
            days=int(reply.split("::",1)[1])
            result=execute_tool("calendar_upcoming",{"days":days,"max_results":20})
            events=result.get("events",[]) if result.get("ok") else []
            if not events:
                reply=f"No tienes eventos en tu calendario durante los próximos {days} días."
            else:
                lines=[f"Estos son tus próximos eventos ({days} día(s)):"]
                for e in events: lines.append(f"• {e.get('start')} — {e.get('summary')}")
                reply="\n".join(lines)
        except Exception as exc:
            reply=f"No he podido consultar Google Calendar: {exc}"

    if isinstance(reply,str) and reply.startswith("HE_EMAIL::"):
        import json as _json
        try:
            draft=_json.loads(reply.split("::",1)[1])
            _set_pending(_pending_email_from(draft))
            set_focus("email_draft", draft.get("subject") or "borrador actual")
            reply = _email_card(draft, question=True)
        except Exception as exc:
            reply=f"No he podido preparar el correo: {exc}"

    _remember_turn("assistant",reply)
    return reply

# Single public HTTP endpoint. Long work is delegated to a background thread.
@app.post("/api/chat")
def chat():
    data = request.get_json(silent=True) or {}
    msg = (data.get("message") or "").strip()
    if not msg:
        return jsonify({"error":"Mensaje vacío"}), 400
    job_id = uuid.uuid4().hex
    user_id = get_current_user()
    _write_job(job_id, "running", user_id=user_id)
    threading.Thread(target=_run_chat_job, args=(job_id, msg, user_id), daemon=True).start()
    return jsonify({"job_id": job_id, "status": "running"}), 202

@app.get("/api/jobs/<job_id>")
def job_status(job_id):
    job = _read_job(job_id)
    if not job:
        return jsonify({"status":"not_found"}), 404
    if job.get("user_id") and job.get("user_id") != get_current_user():
        return jsonify({"status":"not_found"}), 404
    return jsonify(job)

@app.post("/api/studio/command")
def studio_command():
    data=request.get_json(silent=True) or {}
    instruction=(data.get("instruction") or "").strip()
    mode=(data.get("mode") or "image").strip().lower()
    state=data.get("state") or {}
    if not instruction:
        return jsonify({"ok":False,"error":"Falta la orden."}),400
    try:
        if mode == "audio" and data.get("project_id"):
            result=interpret_audio_command(data.get("project_id"), instruction)
            return jsonify(result)
        result=interpret_studio(instruction, mode, state)
        return jsonify(result)
    except Exception as exc:
        return jsonify({"ok":False,"error":str(exc)}),400


@app.post("/api/voice/transcribe")
def voice_transcribe():
    try:
        f = request.files.get("audio")
        if not f:
            return jsonify({"ok": False, "error": "No se recibió audio."}), 400
        result = transcribe_audio(f.stream, f.mimetype or "audio/webm", f.filename or "voz.webm")
        return jsonify({"ok": True, "text": result.get("text", ""), "provider": result.get("provider", "Gemini")})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:900]}), 500

@app.post("/api/voice/tts")
def voice_tts():
    try:
        data = request.get_json(silent=True) or {}
        text = str(data.get("text") or "").strip()
        voice = str(data.get("voice") or "Kore").strip()
        language = str(data.get("language") or "es-ES").strip()
        if not text:
            return jsonify({"ok": False, "error": "Falta el texto."}), 400
        audio, mime = synthesize(text, voice=voice, language=language)
        return jsonify({"ok": True, "mime": mime, "audio_base64": base64.b64encode(audio).decode("ascii"), "provider": "Gemini 3.1 Flash TTS"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:900]}), 500

@app.get("/api/voice/live-token")
def voice_live_token():
    try:
        key = (load().get("api", {}).get("api_key") or os.environ.get("GEMINI_API_KEY", "")).strip()
        if not key:
            return jsonify({"ok": False, "error": "Falta la API key de Gemini."}), 500
        now = datetime.datetime.now(datetime.timezone.utc)
        expire = now + datetime.timedelta(minutes=30)
        new_session = now + datetime.timedelta(minutes=1)
        model = model_for("live")
        payload = {
            "uses": 1,
            "expireTime": expire.isoformat().replace("+00:00", "Z"),
            "newSessionExpireTime": new_session.isoformat().replace("+00:00", "Z"),
            "liveConnectConstraints": {
                "model": f"models/{model}",
                "config": {
                    "responseModalities": ["AUDIO"],
                    "sessionResumption": {},
                },
            },
        }
        r = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/auth_tokens",
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
        if not r.ok:
            return jsonify({"ok": False, "error": f"Gemini token HTTP {r.status_code}: {r.text[:700]}"}), 502
        data = r.json()
        token = data.get("name") or data.get("authToken", {}).get("name")
        if not token:
            return jsonify({"ok": False, "error": "Gemini no devolvió un token efímero."}), 502
        return jsonify({"ok": True, "token": token, "model": model, "expires_at": expire.isoformat()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:900]}), 500

@app.get("/api/studio/audio/projects")
def studio_audio_projects():
    return jsonify({"ok":True,"projects":audio_list_projects()})

@app.post("/api/studio/audio/projects")
def studio_audio_create():
    data=request.get_json(silent=True) or {}
    try:
        return jsonify({"ok":True,"project":audio_create_project(data.get("name",""),data.get("genre","pop"),data.get("bpm"),data.get("duration",30),data.get("root",60),data.get("key","C"))})
    except Exception as exc:return jsonify({"ok":False,"error":str(exc)}),400

@app.patch("/api/studio/audio/projects/<pid>")
def studio_audio_update(pid):
    try:return jsonify({"ok":True,"project":audio_save_settings(pid,request.get_json(silent=True) or {})})
    except Exception as exc:return jsonify({"ok":False,"error":str(exc)}),400

@app.post("/api/studio/audio/reference")
def studio_audio_reference():
    data=request.get_json(silent=True) or {}
    try:
        from .music_reference import analyze_reference
        return jsonify(analyze_reference(data.get("instruction",""), data.get("artist")))
    except Exception as exc:
        return jsonify({"ok":False,"error":str(exc)}),400

@app.post("/api/studio/audio/projects/<pid>/render")
def studio_audio_render(pid):
    try:
        data=request.get_json(silent=True) or {}
        r=audio_render_base(pid, data.get("genre"), data.get("bpm"), data.get("duration"), data.get("root"), data.get("instruments"), data.get("energy",.65), data.get("seed"))
        try:
            from .knowledge import index_artifact
            index_artifact(r.get("file", pid), f"Base de audio · {r.get('genre','')}", f"Base generada por Zar: {r.get('genre','')}, {r.get('bpm')} BPM, {r.get('duration')} s, instrumentos: {', '.join(r.get('instruments') or [])}.", r)
        except Exception:
            pass
        return jsonify({"ok":True,"audio":r})
    except Exception as exc:return jsonify({"ok":False,"error":str(exc)}),400

@app.post("/api/studio/audio/projects/<pid>/voice-effect")
def studio_audio_voice_effect(pid):
    try:
        f=request.files.get('file')
        if not f:return jsonify({"ok":False,"error":"No se recibió audio."}),400
        r=audio_apply_voice_effect(pid,f,request.form.get('effect','clean'))
        return jsonify({"ok":True,"audio":r})
    except Exception as exc:return jsonify({"ok":False,"error":str(exc)}),400

@app.get("/api/studio/audio/projects/<pid>/preview")
def studio_audio_preview(pid):
    name=Path(request.args.get('file','')).name
    path=Path(os.environ.get('ZAR_DATA_DIR','/data'))/'audio_studio'/'outputs'/name
    if not path.exists() or pid not in path.name:return jsonify({"ok":False,"error":"Audio no encontrado."}),404
    return send_file(str(path),mimetype='audio/wav',as_attachment=False,download_name=path.name,conditional=True,etag=True,max_age=0)

@app.get("/api/studio/time")
def studio_time():
    from datetime import datetime
    return jsonify({"ok":True,"iso":datetime.now().astimezone().isoformat()})

@app.get("/api/studio/weather")
def studio_weather():
    import requests as _requests
    try:
        lat=float(request.args.get("lat")); lon=float(request.args.get("lon"))
    except Exception:
        return jsonify({"ok":False,"error":"Faltan coordenadas."}),400
    try:
        r=_requests.get("https://api.open-meteo.com/v1/forecast",params={
            "latitude":lat,
            "longitude":lon,
            "current":"temperature_2m,apparent_temperature,weather_code,wind_speed_10m,wind_direction_10m,wind_gusts_10m,relative_humidity_2m,cloud_cover,precipitation,pressure_msl,is_day",
            "daily":"weather_code,temperature_2m_max,temperature_2m_min,apparent_temperature_max,apparent_temperature_min,precipitation_probability_max,precipitation_sum,sunrise,sunset,uv_index_max,wind_speed_10m_max,wind_gusts_10m_max",
            "forecast_days":7,
            "timezone":"auto"
        },timeout=15)
        r.raise_for_status(); return jsonify({"ok":True,"data":r.json()})
    except Exception as exc:
        return jsonify({"ok":False,"error":str(exc)}),400

@app.get("/api/calendar/month")
def calendar_month_api():
    """Return events for a calendar month so the Zar calendar can render a full grid."""
    from .google_calendar import month_events
    try:
        year=int(request.args.get("year") or datetime.now().year)
        month=int(request.args.get("month") or datetime.now().month)
        if month < 1 or month > 12: raise ValueError("Mes no válido.")
        return jsonify({"ok":True,"year":year,"month":month,"events":month_events(year,month)})
    except Exception as exc:
        return jsonify({"ok":False,"error":str(exc)}),400

@app.get("/api/calendar/upcoming")
def calendar_upcoming_api():
    from .google_calendar import upcoming_events
    try:
        days=int(request.args.get("days") or 7); max_results=int(request.args.get("max_results") or 10)
        return jsonify({"ok":True,"events":upcoming_events(days,max_results)})
    except Exception as exc:
        return jsonify({"ok":False,"error":str(exc)}),400

@app.get("/api/video/projects")
def video_projects():
    return jsonify({"ok": True, "projects": list_projects()})

@app.post("/api/video/projects/from-command")
def video_create_project_from_command():
    """Create a new video project from a natural-language request.
    This intentionally uses a conservative parser: it creates the project shell and
    leaves media selection/editing to the Studio, where Zar can continue the work.
    """
    import re as _re
    data=request.get_json(silent=True) or {}
    text=(data.get("instruction") or "").strip()
    if not text:
        return jsonify({"ok":False,"error":"Falta la petición para crear el proyecto."}),400
    low=text.lower()
    m=_re.search(r'(?:llamado|llamada|titulado|con el nombre|nombre)\s+["“«]?(.+?)["”»]?(?:\.|,| para | en |$)', text, _re.I)
    name=(m.group(1).strip() if m else '')
    if not name:
        name='Proyecto '+datetime.now().strftime('%d-%m-%Y %H-%M')
    preset='tiktok' if 'tiktok' in low else 'shorts' if any(x in low for x in ('short','reel','instagram','vertical','9:16')) else 'square' if 'cuadrad' in low or '1:1' in low else 'youtube'
    mood='energetic' if any(x in low for x in ('energ','dinám','dinam','rápido','rapido')) else 'chill' if 'chill' in low else 'travel' if any(x in low for x in ('viaje','travel','vacaciones')) else 'dramatic' if any(x in low for x in ('dramát','dramat')) else 'cinematic'
    project=create_project(name,preset,mood,'fade',3.2)
    project['editor']['title']=name
    project['editor']['description']=text[:1000]
    try:
        pp=Path(project_path(project['id']))
        pp.write_text(json.dumps(project,ensure_ascii=False,indent=2),encoding='utf-8')
    except Exception:
        pass
    set_last_video_project({"id":project.get("id"),"name":project.get("name","")})
    set_focus("video",project.get("name","proyecto de vídeo"))
    return jsonify({"ok":True,"project":project,"message":"Proyecto creado. Ahora puedes añadir medios y seguir editándolo con Zar."})

@app.post("/api/video/projects")
def video_create_project():
    data = request.get_json(silent=True) or {}
    try:
        project = create_project(data.get("name",""), data.get("preset","youtube"), data.get("music_mood","cinematic"), data.get("transition","crossfade"), data.get("image_duration",3.2))
        set_last_video_project({"id":project.get("id"),"name":project.get("name","")}); set_focus("video", project.get("name","proyecto de vídeo"))
        return jsonify({"ok": True, "project": project})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

@app.get("/api/video/transitions")
def video_transitions():
    return jsonify({"ok":True,"transitions":transition_catalog()})

@app.patch("/api/video/projects/<pid>")
def video_project_update(pid):
    data=request.get_json(silent=True) or {}
    try:
        project=set_project(pid,data)
        set_last_video_project({"id":project.get("id"),"name":project.get("name","")}); set_focus("video",project.get("name","proyecto de vídeo"))
        return jsonify({"ok":True,"project":project})
    except Exception as exc:
        return jsonify({"ok":False,"error":str(exc)}),400

@app.patch("/api/video/projects/<pid>/media/<int:index>")
def video_project_media_update(pid,index):
    try:
        project=update_media(pid,index,request.get_json(silent=True) or {})
        set_last_video_project({"id":project.get("id"),"name":project.get("name","")}); return jsonify({"ok":True,"project":project})
    except Exception as exc:
        return jsonify({"ok":False,"error":str(exc)}),400

@app.delete("/api/video/projects/<pid>/media/<int:index>")
def video_project_media_delete(pid,index):
    try:
        project=delete_media(pid,index); return jsonify({"ok":True,"project":project})
    except Exception as exc:
        return jsonify({"ok":False,"error":str(exc)}),400

@app.post("/api/video/projects/<pid>/move")
def video_project_media_move(pid):
    data=request.get_json(silent=True) or {}
    try:
        project=move_media(pid,data.get("from"),data.get("to")); return jsonify({"ok":True,"project":project})
    except Exception as exc:
        return jsonify({"ok":False,"error":str(exc)}),400

@app.post("/api/video/projects/<pid>/command")
def video_project_command(pid):
    data=request.get_json(silent=True) or {}
    try:
        result=apply_edit_command(pid,data.get("instruction", ""))
        project=result.get("project") or get_project(pid)
        if project: set_last_video_project({"id":project.get("id"),"name":project.get("name","")}); set_focus("video",project.get("name","proyecto de vídeo"))
        return jsonify(result)
    except Exception as exc:
        return jsonify({"ok":False,"error":str(exc)}),400

@app.post("/api/video/projects/<pid>/viral-optimize")
def video_project_viral(pid):
    data=request.get_json(silent=True) or {}
    try:
        result=viral_optimize(pid,data.get("platform","shorts")); project=result.get("project")
        if project: set_last_video_project({"id":project.get("id"),"name":project.get("name","")}); set_focus("video",project.get("name","proyecto de vídeo"))
        return jsonify(result)
    except Exception as exc:
        return jsonify({"ok":False,"error":str(exc)}),400

@app.post("/api/video/projects/<pid>/media")
def video_project_media(pid):
    try:
        files = request.files.getlist("files")
        if not files: return jsonify({"ok": False, "error": "No se recibieron fotos o vídeos."}), 400
        added = [video_add_media(pid, f) for f in files]
        return jsonify({"ok": True, "files": added, "project": get_project(pid)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

@app.post("/api/video/projects/<pid>/music")
def video_project_music(pid):
    try:
        p = get_project(pid)
        if not p: return jsonify({"ok": False, "error": "Proyecto no encontrado."}), 404
        data = request.get_json(silent=True) or {}
        mood = data.get("mood") or p.get("music_mood","cinematic")
        duration = int(data.get("duration") or 30)
        meta = generate_music(pid, mood, duration)
        p["music"] = {k:v for k,v in meta.items() if k != "path"}
        p["music"]["url"] = f'/api/video/projects/{pid}/music-preview?file={quote(Path(meta["path"]).name)}'
        # Persist music metadata using video_creator internals via render later; lightweight sidecar is enough.
        pp = Path(p.get("_path") or str(Path(os.environ.get("ZAR_DATA_DIR","/data"))/"video_creator"/"projects"/f"{pid}.json"))
        p.pop("_path",None)
        pp.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")
        p["_path"] = str(pp)
        return jsonify({"ok": True, "music": p["music"]})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

@app.get("/api/video/projects/<pid>/music-preview")
def video_music_preview(pid):
    file_name = Path(request.args.get("file","")).name
    base = Path(os.environ.get("ZAR_DATA_DIR","/data"))/"video_creator"/"music"
    path = base / file_name
    if not path.exists() or pid not in path.name:
        return jsonify({"ok":False,"error":"Pista no encontrada."}), 404
    return send_file(str(path), mimetype="audio/wav", as_attachment=False, download_name=path.name)

@app.get("/api/video/projects/<pid>/media/<int:index>/preview")
def preview_video_project_media(pid, index):
    p = get_project(pid)
    if not p or index < 1 or index > len(p.get("media", [])):
        return jsonify({"error": "Medio no encontrado."}), 404
    item = p["media"][index-1]
    path = media_path(item)
    if not path.exists():
        return jsonify({"error": "El medio no está disponible."}), 404
    return send_file(path, mimetype=item.get("mime") or None, as_attachment=False, download_name=item.get("name", "medio"))

@app.post("/api/video/projects/<pid>/media/<int:index>/text")
def add_video_text_overlay_api(pid, index):
    try:
        data=request.get_json(silent=True) or {}
        return jsonify({"ok": True, "project": add_text_overlay(pid, index, data)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

@app.patch("/api/video/projects/<pid>/media/<int:index>/text/<overlay_id>")
def update_video_text_overlay_api(pid, index, overlay_id):
    try:
        data=request.get_json(silent=True) or {}
        return jsonify({"ok": True, "project": update_text_overlay(pid, index, overlay_id, data)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

@app.delete("/api/video/projects/<pid>/media/<int:index>/text/<overlay_id>")
def delete_video_text_overlay_api(pid, index, overlay_id):
    try:
        return jsonify({"ok": True, "project": delete_text_overlay(pid, index, overlay_id)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

@app.get("/api/studio/inspiration/search")
def studio_inspiration_search():
    q=(request.args.get("q") or "").strip()
    try:
        limit=int(request.args.get("limit") or 12)
    except Exception:
        limit=12
    return jsonify(search_inspiration_images(q, limit))

@app.post("/api/studio/inspiration/analyze")
def studio_inspiration_analyze():
    data=request.get_json(silent=True) or {}
    return jsonify(analyze_inspiration_image(data.get("url", ""), data.get("instructions", "")))

@app.post("/api/studio/improvement/proposal")
def studio_improvement_proposal():
    data=request.get_json(silent=True) or {}
    analysis=(data.get("analysis") or "").strip()
    goal=(data.get("goal") or "").strip()
    if not analysis:
        return jsonify({"ok":False,"error":"Falta el análisis visual."}), 400
    prompt=(
        "A partir de esta referencia visual y objetivo, redacta una propuesta de mejora para Zar Studio. "
        "No modifiques código ni despliegues nada. Devuelve: nombre del preset, cuándo usarlo, ajustes recomendados "
        "(tipografía, texto, posición, ritmo, transición, color, composición) y qué cambios requieren revisión humana.\n"
        f"Objetivo: {goal or 'mejorar el editor' }\nReferencia analizada:\n{analysis[:12000]}"
    )
    try:
        text=respond(prompt)
        return jsonify({"ok":True,"proposal":text,"requires_approval":True})
    except Exception as exc:
        return jsonify({"ok":False,"error":str(exc)}), 400

@app.post("/api/video/projects/<pid>/render")
def video_project_render(pid):
    data = request.get_json(silent=True) or {}
    p = get_project(pid)
    if not p:
        return jsonify({"ok":False,"error":"Proyecto no encontrado."}), 404
    settings = data.get("settings") or {}
    if settings:
        p["preset"] = settings.get("preset", p.get("preset","youtube"))
        p["transition"] = settings.get("transition", p.get("transition","crossfade"))
        try: p["image_duration"] = max(1.0,min(float(settings.get("image_duration",p.get("image_duration",3.2))),10.0))
        except Exception: pass
        pp = Path(p.get("_path"))
        out = {k:v for k,v in p.items() if k!="_path"}
        pp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    job_id = uuid.uuid4().hex
    _write_job(job_id, "running")
    def worker():
        try:
            result = render_project(pid, bool(data.get("music", True)))
            try:
                from .knowledge import index_artifact
                index_artifact(f"video:{pid}", f"Vídeo generado · {p.get('name','proyecto')}", f"Render del proyecto de vídeo {p.get('name','proyecto')}. Preset: {p.get('preset')}. Salida: {result.get('preview_url') or result.get('path','')}", result)
            except Exception:
                pass
            _write_job(job_id, "done", reply=result.get("preview_url"), action=result)
        except Exception as exc:
            _write_job(job_id, "error", error=str(exc))
    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"ok":True,"job_id":job_id})

@app.get("/api/video/projects/<pid>")
def video_project_get(pid):
    p = get_project(pid)
    if not p: return jsonify({"ok":False,"error":"Proyecto no encontrado."}), 404
    set_last_video_project({"id":p.get("id"),"name":p.get("name","")}); set_focus("video",p.get("name","proyecto de vídeo"))
    return jsonify({"ok":True,"project":p})

@app.get("/api/video/projects/<pid>/preview")
def video_project_preview(pid):
    p = get_project(pid)
    if not p or not p.get("output",{}).get("path") or not Path(p["output"]["path"]).exists():
        return jsonify({"ok":False,"error":"Todavía no hay una exportación para previsualizar."}), 404
    return send_file(p["output"]["path"], mimetype="video/mp4", as_attachment=False, download_name=f"zar_{pid}.mp4")

@app.get("/api/video/projects/<pid>/download")
def video_project_download(pid):
    p = get_project(pid)
    if not p or not p.get("output",{}).get("path") or not Path(p["output"]["path"]).exists():
        return jsonify({"ok":False,"error":"Todavía no hay una exportación."}), 404
    return send_file(p["output"]["path"], mimetype="video/mp4", as_attachment=True, download_name=(re.sub(r'[^\w\-]+','_',p.get('name','zar_video'))[:80]+'.mp4'))

@app.get("/api/persistence/status")
def persistence_status_api():
    """Resumen de lo que ZAR conserva fuera del código de la versión desplegada."""
    try:
        from .knowledge import stats as knowledge_stats
        kstats = knowledge_stats()
    except Exception:
        kstats = {"sources": 0, "chunks": 0}
    try:
        reports = list_reports(5000)
    except Exception:
        reports = []
    try:
        convs = list_conversations(5000)
    except Exception:
        convs = []
    try:
        mems = memories()
    except Exception:
        mems = []
    try:
        files = list_files()
    except Exception:
        files = []
    data_dir = str(os.environ.get("ZAR_DATA_DIR") or "")
    persistent = bool(data_dir and (data_dir == "/data" or "LOCALAPPDATA" in data_dir.upper() or ".zar" in data_dir.lower()))
    return jsonify({
        "ok": True,
        "storage": {
            "data_dir": data_dir or "data/",
            "persistent_target": persistent,
            "note": "Los datos de usuario viven fuera del código de la versión; en Railway requieren un Volume montado en /data."
        },
        "conversations": len(convs),
        "memories": len(mems),
        "files": len(files),
        "research_reports": len(reports),
        "knowledge_sources": int(kstats.get("sources", 0) or 0),
        "knowledge_chunks": int(kstats.get("chunks", 0) or 0),
    })


@app.get("/api/files/context")
def files_context_api():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"ok": False, "error": "Falta la búsqueda."}), 400
    try:
        from .knowledge import file_context_for
        return jsonify({"ok": True, "query": q, "context": file_context_for(q, limit=8, max_chars=14000)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 200


@app.post("/api/files/upload")
def upload_file():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No se recibió ningún archivo."}), 400
    note = (request.form.get("note") or "").strip()
    saved = []
    errors = []
    for fs in files:
        try:
            item = save_upload(fs, note=note)
            saved.append(public_item(item))
            try:
                index_file_from_disk(item, files_dir() / item.get("category", "sin_clasificar") / item.get("stored_name", ""))
            except Exception as exc:
                item["knowledge_index_error"] = str(exc)
            set_last_uploaded_file(item)
            set_focus("file", item.get("name", "archivo"))
            set_task_state("guardar archivo", "file", item.get("id", ""), "guardar", "low", "file_saved", f"Archivo guardado: {item.get('name')}")
        except Exception as exc:
            errors.append(str(exc))
    if not saved:
        return jsonify({"error": errors[0] if errors else "No se pudo guardar el archivo."}), 400
    return jsonify({"ok": True, "files": saved, "errors": errors})

@app.get("/api/files")
def files_api():
    category = (request.args.get("category") or "").strip()
    query = (request.args.get("q") or "").strip()
    items = search_files(query, category, 500) if query else list_files(category)[:500]
    return jsonify({"ok": True, "files": [public_item(x) for x in items]})

@app.post("/api/files/<file_id>/analyze")
def analyze_file_api(file_id):
    try:
        from .file_analysis import analyze_file
    except ImportError:
        from file_analysis import analyze_file
    try:
        return jsonify(analyze_file(file_id))
    except Exception as exc:
        text = str(exc)
        if "429" in text and "OpenRouter" in text:
            return jsonify({"ok": False, "error": "El límite gratuito de OpenRouter está agotado. El archivo sí sigue guardado; el análisis visual de V21 usa Gemini y puede repetirse sin volver a subirlo."}), 200
        return jsonify({"ok": False, "error": text}), 200

@app.get("/api/files/<file_id>/preview")
def preview_file(file_id):
    item = get_file(file_id)
    if not item:
        return jsonify({"error":"Archivo no encontrado."}), 404
    path = files_dir() / item.get("category", "sin_clasificar") / item.get("stored_name", "")
    if not path.exists():
        return jsonify({"error":"El archivo no está disponible en el almacenamiento."}), 404
    mime = (item.get("mime") or mimetypes.guess_type(str(path))[0] or "application/octet-stream").lower()
    ext = path.suffix.lower()
    if mime in {"text/plain", "text/csv"} or ext in {".txt", ".csv"}:
        text = path.read_text(encoding="utf-8", errors="replace")
        if ext == ".csv" or mime == "text/csv":
            import csv, io
            rows = list(csv.reader(io.StringIO(text)))[:500]
            html = '<table>' + ''.join('<tr>' + ''.join(('<th>' if ri == 0 else '<td>') + html_lib.escape(c) + ('</th>' if ri == 0 else '</td>') for c in row) + '</tr>' for ri, row in enumerate(rows)) + '</table>' if rows else '<p>Archivo vacío.</p>'
            return jsonify({"ok": True, "kind": "html", "html": '<div class="docPreview">' + html + '</div>'})
        return jsonify({"ok": True, "kind": "html", "html": '<div class="docPreview"><pre>' + html_lib.escape(text[:500000]) + '</pre></div>'})
    if mime in {"application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/msword"} or ext == ".docx":
        try:
            from docx import Document
            doc = Document(str(path)); parts=[]
            for para in doc.paragraphs:
                txt=para.text.strip()
                if txt: parts.append('<p>'+html_lib.escape(txt)+'</p>')
            for table in doc.tables:
                rows=[]
                for row in table.rows: rows.append('<tr>'+''.join('<td>'+html_lib.escape(cell.text)+'</td>' for cell in row.cells)+'</tr>')
                parts.append('<table>'+''.join(rows)+'</table>')
            return jsonify({"ok": True, "kind":"html", "html":'<div class="docPreview">'+''.join(parts or ['<p>Documento sin texto extraíble.</p>'])+'</div>'})
        except Exception as exc:
            return jsonify({"ok":False,"error":"No se pudo generar la vista previa DOCX: "+str(exc)}), 200
    if mime == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" or ext == ".xlsx":
        try:
            from openpyxl import load_workbook
            wb=load_workbook(str(path), read_only=True, data_only=True); chunks=[]
            for ws in wb.worksheets[:10]:
                rows=[]
                for row in ws.iter_rows(max_row=200, values_only=True):
                    vals=["" if v is None else str(v) for v in row]
                    if any(vals): rows.append('<tr>'+''.join('<td>'+html_lib.escape(v)+'</td>' for v in vals)+'</tr>')
                chunks.append('<h3>'+html_lib.escape(ws.title)+'</h3><table>'+''.join(rows)+'</table>')
            return jsonify({"ok":True,"kind":"html","html":'<div class="docPreview">'+''.join(chunks or ['<p>Hoja de cálculo vacía.</p>'])+'</div>'})
        except Exception as exc:
            return jsonify({"ok":False,"error":"No se pudo generar la vista previa XLSX: "+str(exc)}), 200
    if mime == "application/vnd.openxmlformats-officedocument.presentationml.presentation" or ext == ".pptx":
        try:
            from pptx import Presentation
            prs=Presentation(str(path)); parts=[]
            for si,slide in enumerate(prs.slides,1):
                parts.append('<h3>Diapositiva '+str(si)+'</h3>')
                for shape in slide.shapes:
                    if hasattr(shape,'text') and shape.text.strip(): parts.append('<p>'+html_lib.escape(shape.text).replace('\n','<br>')+'</p>')
            return jsonify({"ok":True,"kind":"html","html":'<div class="docPreview">'+''.join(parts or ['<p>Presentación sin texto extraíble.</p>'])+'</div>'})
        except Exception as exc:
            return jsonify({"ok":False,"error":"No se pudo generar la vista previa PPTX: "+str(exc)}), 200
    return send_file(path, mimetype=mime, as_attachment=False, download_name=item.get("name", "archivo"))

@app.get("/api/files/<file_id>/download")
def download_file(file_id):
    item = get_file(file_id)
    if not item:
        return jsonify({"error": "Archivo no encontrado."}), 404
    path = files_dir() / item.get("category", "sin_clasificar") / item.get("stored_name", "")
    if not path.exists():
        return jsonify({"error": "El archivo no está disponible en el almacenamiento."}), 404
    return send_file(path, as_attachment=True, download_name=item.get("name", "archivo"), mimetype=item.get("mime") or None)

@app.delete("/api/files/<file_id>")
def remove_file(file_id):
    return jsonify({"ok": delete_file(file_id)})

@app.post("/api/context/reset")
def reset_chat_context():
    clear_conversation(archive=True)
    reset_context(clear_email=True)
    return jsonify({"ok": True})

@app.get("/api/conversations")
def conversations_api():
    return jsonify({"ok": True, "conversations": list_conversations(80)})

@app.get("/api/conversations/<thread_id>")
def conversation_archive_api(thread_id):
    item = get_conversation_archive(thread_id)
    if not item:
        return jsonify({"ok": False, "error": "Conversación no encontrada."}), 404
    return jsonify({"ok": True, "conversation": item})

@app.post("/api/memory")
def add_memory():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error":"Texto vacío"}),400
    return jsonify(remember(text))

@app.delete("/api/memory/<memory_id>")
def remove_memory(memory_id):
    return jsonify({"memories":delete_memory(memory_id)})

@app.get("/api/memory/search")
def memory_search_api():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"ok": False, "error": "Falta la búsqueda."}), 400
    return jsonify({"ok": True, "results": search_memory(q, request.args.get("limit", 12)), "stats": memory_stats()})

@app.get("/api/memory/stats")
def memory_stats_api():
    return jsonify({"ok": True, "stats": memory_stats()})

@app.get("/api/memory/insights")
def memory_insights_api():
    return jsonify({"ok": True, "stats": memory_stats(), "insights": memory_insights()})

@app.get("/api/memory/3")
def memory3_api():
    try:
        st = memory3_stats()
        if st.get("total", 0) == 0:
            legacy = memories()
            if legacy:
                memory3_reindex(legacy)
                st = memory3_stats()
        return jsonify({"ok": True, "stats": st, "recent": memory3_recent(30)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

@app.get("/api/memory/3/search")
def memory3_search_api():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"ok": False, "error": "Falta la búsqueda."}), 400
    return jsonify({"ok": True, "results": memory3_search(q, request.args.get("limit", 12)), "stats": memory3_stats()})

@app.post("/api/memory/3/reindex")
def memory3_reindex_api():
    try:
        return jsonify({"ok": True, **memory3_reindex(memories())})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

# V27.9 Studio Pro: persistent publication queue. Platform APIs are intentionally
# separated from the editor so a future OAuth connector can publish without
# changing the project model.
PUB_DIR = Path(os.environ.get('ZAR_DATA_DIR', '/data')) / 'video_creator' / 'publications'
PUB_DIR.mkdir(parents=True, exist_ok=True)

def _pub_file():
    return PUB_DIR / 'queue.json'

def _load_publications():
    f = _pub_file()
    if not f.exists(): return []
    try:
        data = json.loads(f.read_text(encoding='utf-8'))
        return data if isinstance(data, list) else []
    except Exception:
        return []

def _save_publications(items):
    f = _pub_file(); tmp = f.with_suffix('.tmp')
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding='utf-8'); tmp.replace(f)

@app.get('/api/youtube/videos/<video_id>')
def api_youtube_video_status(video_id):
    try:
        return jsonify({'ok': True, 'video': youtube_video_status(video_id)})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400

@app.get('/api/video/publications')
def video_publications():
    return jsonify({'ok': True, 'publications': _load_publications()})

@app.post('/api/video/projects/<pid>/publication')
def video_create_publication(pid):
    p = get_project(pid)
    if not p: return jsonify({'ok':False,'error':'Proyecto no encontrado.'}),404
    data = request.get_json(silent=True) or {}
    platform = str(data.get('platform') or '').lower()
    if platform not in {'youtube','instagram','tiktok','whatsapp','email'}:
        return jsonify({'ok':False,'error':'Plataforma no válida.'}),400
    action = str(data.get('action') or 'schedule').lower()
    if action not in {'now','schedule'}:
        return jsonify({'ok':False,'error':'Acción no válida.'}),400
    if action == 'schedule' and not data.get('scheduled_at'):
        return jsonify({'ok':False,'error':'Indica fecha y hora para programar.'}),400
    if not data.get('confirmed'):
        return jsonify({'ok':False,'error':'La publicación debe confirmarse antes de crearla.'}),400
    title = str(data.get('title') or p.get('editor',{}).get('title') or p.get('name') or 'Vídeo de Zar')[:200]
    description = str(data.get('description') or p.get('editor',{}).get('description') or '')[:5000]
    if platform == 'youtube':
        output_path = (p.get('output') or {}).get('path')
        if not output_path or not Path(output_path).exists():
            return jsonify({'ok':False,'error':'Primero renderiza el vídeo para poder subirlo a YouTube.'}),400
        pub_id = uuid.uuid4().hex
        item = {
            'id': pub_id, 'project_id': pid, 'project_name': p.get('name',''), 'platform': platform,
            'action': action, 'status': 'uploading', 'scheduled_at': data.get('scheduled_at'),
            'title': title, 'description': description, 'created_at': datetime.now().astimezone().isoformat(),
            'output_url': f'/api/video/projects/{pid}/preview', 'video_id': None, 'youtube_url': None,
        }
        items = _load_publications(); items.insert(0,item); _save_publications(items[:200])
        def worker():
            try:
                privacy = 'private' if action == 'schedule' else 'public'
                result = youtube_upload(output_path, title, description, tags=data.get('tags') or [], privacy=privacy, publish_at=data.get('scheduled_at') if action == 'schedule' else None)
                video_id = result.get('id')
                items2 = _load_publications()
                for x in items2:
                    if x.get('id') == pub_id:
                        x['video_id'] = video_id
                        x['youtube_url'] = f'https://www.youtube.com/watch?v={video_id}' if video_id else None
                        x['status'] = 'scheduled' if action == 'schedule' else 'uploaded'
                        x['privacy_status'] = (result.get('status') or {}).get('privacyStatus')
                        x['youtube_response'] = {'id': video_id, 'privacyStatus': x['privacy_status']}
                        break
                _save_publications(items2[:200])
            except Exception as exc:
                items2 = _load_publications()
                for x in items2:
                    if x.get('id') == pub_id:
                        x['status'] = 'error'; x['error'] = str(exc)
                        break
                _save_publications(items2[:200])
        threading.Thread(target=worker, daemon=True).start()
        return jsonify({'ok':True,'publication':item,'message':'Subida de YouTube iniciada. ZAR te mostrará el resultado en la cola.'})
    item = {
        'id': uuid.uuid4().hex,
        'project_id': pid,
        'project_name': p.get('name',''),
        'platform': platform,
        'action': action,
        'status': 'scheduled' if action == 'schedule' else 'confirmed',
        'scheduled_at': data.get('scheduled_at'),
        'title': title,
        'description': description,
        'created_at': datetime.now().astimezone().isoformat(),
        'output_url': f'/api/video/projects/{pid}/preview' if p.get('output') else None,
    }
    items = _load_publications(); items.insert(0,item); _save_publications(items[:200])
    return jsonify({'ok':True,'publication':item,'message':'Publicación confirmada y guardada en la cola.'})

@app.delete('/api/video/publications/<pubid>')
def video_cancel_publication(pubid):
    items=_load_publications(); new=[x for x in items if x.get('id')!=pubid]
    if len(new)==len(items): return jsonify({'ok':False,'error':'Publicación no encontrada.'}),404
    _save_publications(new); return jsonify({'ok':True})


@app.get("/api/models")
def api_models():
    """Expose the active ZAR multi-model map without exposing API keys."""
    try:
        from .model_router import catalog
    except ImportError:
        from model_router import catalog
    return jsonify({"ok": True, "models": catalog()})

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT','8765')), debug=False)
