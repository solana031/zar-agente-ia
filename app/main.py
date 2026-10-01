# ZAR v30.3.0 — Memoria + Archivos 2.0
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
from functools import wraps
from contextlib import contextmanager
from . import stonks_lifecycle, stonks_preflight, stonks_agents, stonks_news, subagent_orchestrator, stonks_backtest, stonks_validation
from datetime import datetime, timezone
from .user_scope import set_current_user, get_current_user, anonymous_id, user_id_for_email
from pathlib import Path
from .cloud_auth import authorization_url, finish_oauth, connected, auth_status, get_credentials
from .youtube_auth import authorization_url as youtube_authorization_url, finish_oauth as finish_youtube_oauth, status as youtube_auth_status
from .agent import respond, summarize_email, draft_reply_email, revise_email_draft
from .tools import TOOL_DEFINITIONS, execute_tool
from .memory import memories, remember, delete_memory, history, add_message, conversation, add_conversation_message, clear_conversation, list_conversations, get_conversation_archive, update_conversation_archive
from .config import load, save
from .google_calendar import calendar_status
from .gmail import gmail_status
from .google_workspace import workspace_status
from .google_backup import start_google_backup, backup_status, normalize_backup_options
from .context import get_context, set_active_email, set_pending_email, mark_saved_draft, clear_pending, set_summary, reset_context, set_pending_calendar, clear_pending_calendar, set_focus, clear_focus, set_task_state, clear_task_state, set_last_uploaded_file, set_pending_workspace, clear_pending_workspace, set_last_contact, set_media, set_last_video_project
from .file_store import save_upload, get_file, list_files, search_files, public_item, delete_file, files_dir, DuplicateFileError
from .knowledge import context_for as memory_context_for, search as search_memory, stats as memory_stats, memory_insights, index_file_from_disk, bootstrap_from_legacy
from .memory3 import stats as memory3_stats, recent as memory3_recent, search as memory3_search, reindex_existing as memory3_reindex
from .web_search import search_inspiration_images, analyze_inspiration_image
from .deep_research import start_research, wait_for_research, save_report, list_reports, get_report, get_research, extract_report
from .skills import list_skills, get_skill, create_skill, update_skill, delete_skill, execute_skill, match_skill
from .learning import list_learning, list_jobs, get_job, start_learning, resume_learning, learn_from_file, active_learning_count, delete_learning, advance_learning, _ensure_learning_worker
from .video_creator import create_project, list_projects, get_project, project_path, add_media as video_add_media, generate_music, render_project, media_path, set_project, update_media, delete_media, move_media, split_media, transition_catalog, apply_edit_command, viral_optimize, add_text_overlay, update_text_overlay, delete_text_overlay
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

TEMPLATE_OAUTH_SUCCESS = "<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta name='theme-color' content='#090807'><title>Zar · Conexión correcta</title><style>*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#090807;color:#f3ece4;font-family:Inter,system-ui,sans-serif;overflow:hidden}.bg{position:fixed;inset:0;background:linear-gradient(90deg,rgba(9,8,7,.2),rgba(9,8,7,.82)),url('/static/zar-dog.png') left center/cover no-repeat;filter:brightness(.7) saturate(.75);transform:scale(1.03)}.veil{position:fixed;inset:0;background:radial-gradient(circle at 50% 35%,rgba(215,169,100,.16),transparent 38%),linear-gradient(180deg,rgba(7,6,5,.25),rgba(7,6,5,.84))}.box{position:relative;width:min(720px,calc(100% - 30px));padding:32px;border:1px solid rgba(215,169,100,.5);border-radius:26px;background:rgba(20,15,11,.76);backdrop-filter:blur(18px);box-shadow:0 30px 100px rgba(0,0,0,.62);text-align:center}.dog{width:92px;height:76px;object-fit:cover;object-position:center 38%;border-radius:20px;margin:0 auto 12px;display:block}.oauthOk{width:64px;height:64px;border-radius:50%;display:grid;place-items:center;margin:6px auto 12px;border:1px solid rgba(215,169,100,.65);background:rgba(215,169,100,.12);font-size:34px;color:#e5c58e}.svc{min-height:72px;display:flex;flex-direction:column;align-items:center;justify-content:center;box-sizing:border-box}.svc span{display:block;font-size:20px;line-height:1;margin:0 0 6px}.svc b{display:block;font-size:10px;line-height:1.2}.svc small{display:block;font-size:8px;line-height:1.2;color:#8e8379;margin-top:5px}h1{font:700 38px Georgia,serif;color:#ead0a5;margin:0 0 8px}p{color:#b9aea3;font-size:14px;line-height:1.55;margin:8px 0}.services{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:20px 0}.svc{padding:11px 7px;border:1px solid #4a3828;border-radius:12px;background:rgba(8,7,6,.55);color:#d8cabb}.svc.ok{border-color:rgba(113,167,109,.55)}.svc.pending{border-color:rgba(185,145,76,.5)}.svc span{display:block;font-size:20px;margin-bottom:4px}.svc b{display:block;font-size:10px}.svc small{display:block;font-size:8px;color:#8e8379;margin-top:3px}.btn{display:inline-block;margin-top:12px;padding:12px 24px;border:1px solid #9d713c;border-radius:13px;background:linear-gradient(180deg,#ddb776,#bd8a4c);color:#1a120a;font-weight:800;text-decoration:none}small.note{display:block;margin-top:10px;color:#81766d}@media(max-width:560px){.box{padding:24px 16px}.services{grid-template-columns:repeat(2,1fr)}h1{font-size:32px}}</style></head><body><div class='bg'></div><div class='veil'></div><div class='box'><img class='dog' src='/static/zar-dog.png'><div class='oauthOk'>✓</div><h1>Conexión correcta</h1><p><strong>__LABEL__ conectado</strong></p><p>__DETAIL__</p><div class='services'>__CHIPS__</div><a class='btn' href='/'>Abrir Zar →</a><small class='note'>Volviendo automáticamente a Zar…</small></div><script>setTimeout(function(){try{if(window.opener&&!window.opener.closed){window.opener.postMessage({type:'zar-oauth-success'},window.location.origin);try{window.opener.focus()}catch(e){}setTimeout(function(){try{window.close()}catch(e){}},300);return}}catch(e){}window.location.href='/'},1100);</script></body></html>"

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

def _write_job(job_id, status, reply=None, error=None, action=None, user_id=None, skills=None):
    payload = {"status": status}
    if user_id: payload["user_id"] = user_id
    if action is not None:
        payload["action"] = action
    if reply is not None:
        payload["reply"] = reply
    if error is not None:
        payload["error"] = error
    if skills is not None:
        payload["skills"] = skills
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
    """Devuelve una tarjeta de correo estructurada para que la UI la renderice sin Markdown crudo."""
    blocked = _is_noreply(draft.get("to", ""))
    payload = {
        "kind": "draft",
        "to": draft.get("to", ""),
        "subject": draft.get("subject", ""),
        "body": draft.get("body", ""),
        "question": bool(question),
        "noreply": bool(blocked),
        "reply_to_message_id": draft.get("reply_to_message_id", ""),
        "thread_id": draft.get("thread_id", ""),
    }
    return "ZAR_EMAIL_CARD::" + json.dumps(payload, ensure_ascii=False)


def _email_message_card(email, summary=None, draft=None, title="Correo de Gmail"):
    """Construye un payload visual para correo leído, resumen y/o borrador."""
    payload = {
        "kind": "message",
        "title": title,
        "from": email.get("from", ""),
        "to": email.get("to", ""),
        "subject": email.get("subject", "") or "(sin asunto)",
        "date": email.get("date", ""),
        "body": email.get("text", ""),
    }
    if summary is not None:
        payload["summary"] = summary
    if draft is not None:
        payload["draft"] = {
            "to": draft.get("to", ""),
            "subject": draft.get("subject", ""),
            "body": draft.get("body", ""),
            "question": True,
            "noreply": bool(_is_noreply(draft.get("to", ""))),
        }
        payload["kind"] = "compound"
    return "ZAR_EMAIL_CARD::" + json.dumps(payload, ensure_ascii=False)


def _email_summary_card(email, summary):
    payload = {
        "kind": "summary",
        "from": email.get("from", ""),
        "to": email.get("to", ""),
        "subject": email.get("subject", "") or "(sin asunto)",
        "date": email.get("date", ""),
        "summary": summary or "",
    }
    return "ZAR_EMAIL_CARD::" + json.dumps(payload, ensure_ascii=False)


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
        # v30.2.8: una conexión/reautorización de Google NO inicia una copia automáticamente.
        # La copia debe ser siempre explícita para que el usuario pueda seleccionar qué guardar.
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
    # v30.2.8: abrir Zar o tener Google conectado NO inicia copias automáticamente.
    # El usuario debe pulsar "Configurar y crear copia" y elegir el contenido.
    if not status.get("connected"):
        return _google_login_page(status)
    return render_template("index.html")


# --- ZAR Stonks control plane (broker-agnostic, paper-first) ---
_STONKS_DIR = Path(os.environ.get('ZAR_DATA_DIR', '/data')) / 'stonks'
_STONKS_DIR.mkdir(parents=True, exist_ok=True)
# Serialize worker and HTTP mutations across threads/processes on the persistent volume.
_STONKS_LOCK = threading.RLock()
_STONKS_LOCK_DEPTH = threading.local()

@contextmanager
def _stonks_transaction():
    with _STONKS_LOCK:
        depth = getattr(_STONKS_LOCK_DEPTH, 'value', 0)
        _STONKS_LOCK_DEPTH.value = depth + 1
        try:
            if depth or os.name == 'nt':
                yield
            else:
                import fcntl
                with open(_STONKS_DIR / 'state.lock', 'a+') as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX)
                    try:
                        yield
                    finally:
                        fcntl.flock(lock, fcntl.LOCK_UN)
        finally:
            _STONKS_LOCK_DEPTH.value = depth


def _stonks_serialized(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with _stonks_transaction():
            return fn(*args, **kwargs)
    return wrapped


def _stonks_atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with open(temp, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        if os.name != 'nt':
            fd = os.open(str(path.parent), os.O_RDONLY)
            try: os.fsync(fd)
            finally: os.close(fd)
    finally:
        if temp.exists(): temp.unlink()


def _stonks_file():
    return _STONKS_DIR / f"{_user_scope_id()}.json"
def _stonks_default():
    return {
        'paused': True, 'revoked': True, 'mode': 'paper',
        'max_trade_eur': 25, 'max_daily_loss_eur': 10, 'max_position_pct': 20,
        'execution_mode': 'decision',
        'autonomous_engine': False,
        'engine_symbols': ['AAPL'],
        'engine_strategy': 'trend',
        'engine_timeframe': '1Min',
        'engine_last_run': None,
        'engine_last_action': None,
        'last_executed_signals': {},
        'engine_last_positions': [],
        'engine_last_open_orders': [],
        'engine_last_reconcile': None,
        'engine_last_state_signature': '',
        'position_lifecycle_enabled': False,
        'stop_loss_pct': 1.0,
        'take_profit_pct': 2.0,
        'pending_entries': {},
        'position_ledger': {},
        'paper_connected': False,
        'managed_positions': {},
        'lifecycle_last_action': None,
        'agent_last_trace': [],
        'agent_architecture': 'deterministic_multi_agent',
        'shadow_log': [],
        'shadow_last_run': None,
        'shadow_total_signals': 0,
        'shadow_cycle_total': 0,
        'shadow_last_cycle': None,
        'shadow_last_reason': None,
        'shadow_last_market_open': None,
        'shadow_last_signal_count': 0
    }
def _stonks_read():
    p = _stonks_file()
    if not p.exists():
        return _stonks_default()
    # Corrupt state must fail closed, never silently lose ownership/kill switches.
    d = json.loads(p.read_text(encoding='utf-8'))
    if not isinstance(d, dict):
        raise RuntimeError('Estado Stonks no válido; ejecución bloqueada')
    base = _stonks_default()
    base.update(d)
    return base


def _stonks_write(d):
    _stonks_atomic_json(_stonks_file(), d)


def _stonks_audit_file():
    return _STONKS_DIR / f"{_user_scope_id()}_audit.json"

def _stonks_audit_read(limit=100):
    try:
        p=_stonks_audit_file()
        if p.exists():
            data=json.loads(p.read_text(encoding='utf-8'))
            return data[-limit:] if isinstance(data,list) else []
    except Exception:
        pass
    return []

def _stonks_engine_owner_file():
    return _STONKS_DIR / 'engine_owner.json'

def _stonks_engine_owner_read():
    try:
        p=_stonks_engine_owner_file()
        if p.exists():
            d=json.loads(p.read_text(encoding='utf-8'))
            return str(d.get('scope_id') or '')
    except Exception:
        pass
    return ''

def _stonks_engine_owner_write(scope_id):
    p=_stonks_engine_owner_file(); p.parent.mkdir(parents=True, exist_ok=True)
    if scope_id:
        _stonks_atomic_json(p, {'scope_id':str(scope_id),'updated_at':datetime.now(timezone.utc).isoformat()})
    elif p.exists():
        try: p.unlink()
        except Exception: pass

def _stonks_order_history(after):
    """ID cursor pagination avoids losing fills at equal submission timestamps."""
    rows, seen = [], set()
    cutoff = stonks_lifecycle.timestamp(after)
    params = {'status':'all', 'limit':500, 'direction':'desc', 'nested':'false', 'after':after}
    for _ in range(100):
        page = _alpaca_paper_request('/v2/orders', params=dict(params))
        if not isinstance(page, list):
            raise RuntimeError('Historial Paper no válido')
        if any(not o.get('id') or o['id'] in seen for o in page):
            raise RuntimeError('Historial Paper repetido/incompleto; ejecución bloqueada')
        rows.extend(page)
        seen.update(o['id'] for o in page)
        if len(page) < 500 or stonks_lifecycle.timestamp(page[-1]['submitted_at']) <= cutoff:
            return rows
        params.pop('after', None)
        params['before_order_id'] = page[-1]['id']
    raise RuntimeError('Historial Paper demasiado largo; ejecución bloqueada')


def _stonks_reconcile_paper_state(scope_id, symbols=None, emit_audit=True):
    # Never filter ownership by the current watchlist: removed symbols still need protection.
    try:
        account = _alpaca_paper_request('/v2/account')
    except Exception:
        account = {}  # Connection UI fails closed; observational position reconciliation can continue.
    if not isinstance(account, dict): account = {}
    positions = _alpaca_paper_request('/v2/positions')
    orders = _alpaca_paper_request('/v2/orders', params={'status':'open','limit':500,'nested':'false'})
    if not isinstance(positions, list) or not isinstance(orders, list) or len(orders) >= 500:
        raise RuntimeError('Snapshot Paper incompleto; ejecución bloqueada')
    d = _stonks_read()
    active = stonks_lifecycle.active_records(d)
    history = _stonks_order_history(stonks_lifecycle.history_start(active)) if active else []
    d['paper_connected'] = account.get('status') == 'ACTIVE' and not (account.get('trading_blocked') or account.get('account_blocked'))
    d['engine_last_positions'] = positions
    d['engine_last_open_orders'] = orders
    d['engine_last_reconcile'] = datetime.now(timezone.utc).isoformat()
    signature = json.dumps({'positions':positions, 'orders':orders}, sort_keys=True)
    changed = signature != d.get('engine_last_state_signature')
    d['engine_last_state_signature'] = signature
    _stonks_write(d)
    if emit_audit and changed:
        _stonks_audit_append('RECONCILIACIÓN PAPER', {'position_count':len(positions), 'open_order_count':len(orders)})
    return {'positions':positions, 'open_orders':orders, 'history':history, 'changed':changed}


def _stonks_lookup_order(cid):
    return _alpaca_paper_request('/v2/orders:by_client_order_id', params={'client_order_id':cid}, missing_ok=True)


def _stonks_submit_paper_order(body):
    # Fixed Paper URL + Paper-only credential names; caller holds the state transaction.
    key, secret = _alpaca_paper_credentials()
    if not key or not secret:
        raise RuntimeError('Credenciales Paper no configuradas')
    response = requests.post('https://paper-api.alpaca.markets/v2/orders',
        headers={'APCA-API-KEY-ID':key, 'APCA-API-SECRET-KEY':secret}, json=body, timeout=12)
    if not response.ok:
        raise RuntimeError('Orden Paper no confirmada; reconciliar identificador antes de reintentar')
    order = response.json()
    if not isinstance(order, dict) or not order.get('id'):
        raise RuntimeError('Respuesta Paper no válida')
    return order


def _stonks_manage_positions(scope_id, recon, clock=None):
    d = _stonks_read()
    # Old releases did not prove a flat baseline before submitting. Never adopt ambiguous lots.
    for symbol, row in d.get('managed_positions', {}).items():
        if not row.get('client_order_id'):
            reason = 'Ownership anterior a 31.3.20 sin baseline verificable; revisión manual requerida'
            if row.get('reason') != reason:
                _stonks_audit_append('POSITION_ERROR', {'symbol':symbol, 'reason':reason})
            row.update(symbol=symbol, status='ERROR', reason=reason)
    for symbol, meta in d.get('pending_entries', {}).items():
        if symbol not in d['managed_positions']:
            d['managed_positions'][symbol] = {**meta, 'symbol':symbol, 'status':'ERROR',
                'reason':'Entrada antigua sin baseline verificable; revisión manual requerida'}
    return stonks_lifecycle.manage(d, recon['positions'], recon['history'] + recon['open_orders'],
        _stonks_lookup_order, _stonks_submit_paper_order, _stonks_write, _stonks_audit_append,
        lambda: _alpaca_paper_request('/v2/account'), clock or {'is_open':False},
        cancel=lambda order_id: _alpaca_paper_request('/v2/orders/'+order_id, method='DELETE'))


def _stonks_audit_append(event, details=None):
    rows=_stonks_audit_read(200)
    rows.append({
        'id':uuid.uuid4().hex,
        'timestamp':datetime.now(timezone.utc).isoformat(),
        'event':str(event or 'EVENT'),
        'details':details if isinstance(details,dict) else {'message':str(details or '')}
    })
    rows=rows[-200:]
    _stonks_atomic_json(_stonks_audit_file(), rows)
    return rows[-1]

def _alpaca_paper_credentials():
    return (os.environ.get('ALPACA_PAPER_API_KEY','').strip(), os.environ.get('ALPACA_PAPER_API_SECRET','').strip())

def _alpaca_paper_request(path, method='GET', params=None, missing_ok=False):
    key, secret = _alpaca_paper_credentials()
    if not key or not secret:
        raise RuntimeError('Faltan ALPACA_PAPER_API_KEY y ALPACA_PAPER_API_SECRET en Railway.')
    import requests as _requests
    base='https://paper-api.alpaca.markets'
    r=_requests.request(method, base+path, headers={'APCA-API-KEY-ID':key,'APCA-API-SECRET-KEY':secret,'Accept':'application/json'}, params=params, timeout=12)
    if missing_ok and r.status_code == 404:
        return None
    try: data=r.json()
    except Exception: data={}
    if not r.ok:
        raise RuntimeError(f'Alpaca Paper HTTP {r.status_code}; consulta no confirmada')
    return data

def _alpaca_market_request(path, method='GET', params=None):
    key, secret = _alpaca_paper_credentials()
    if not key or not secret:
        raise RuntimeError('Faltan ALPACA_PAPER_API_KEY y ALPACA_PAPER_API_SECRET en Railway.')
    import requests as _requests
    base='https://data.alpaca.markets'
    r=_requests.request(method, base+path, headers={'APCA-API-KEY-ID':key,'APCA-API-SECRET-KEY':secret,'Accept':'application/json'}, params=params, timeout=12)
    try: data=r.json()
    except Exception: data={'raw':r.text[:1000]}
    if not r.ok:
        msg=data.get('message') if isinstance(data,dict) else None
        raise RuntimeError(f'Alpaca Market Data {r.status_code}: {msg or "respuesta no válida"}')
    return data

@_stonks_serialized
def _stonks_engine_cycle(scope_id):
    """Run one autonomous Paper cycle for the single authorized Stonks owner.
    Reconciliation always runs; orders require explicit persisted authorization.
    """
    with app.test_request_context('/api/stonks/engine/cycle', method='POST'):
        session['zar_user_id']=scope_id
        d=_stonks_read()
        symbols=d.get('engine_symbols') or ['AAPL']
        strategy=d.get('engine_strategy') or 'trend'
        timeframe=d.get('engine_timeframe') or '1Min'
        try:
            agent_trace=[]
            recon, clock, market_trace = stonks_agents.SUPERVISOR.market.snapshot(
                scope_id, _stonks_reconcile_paper_state, lambda: _alpaca_paper_request('/v2/clock'))
            agent_trace.append(market_trace)
            # Public-news context is cached and observational only. It never creates orders.
            news_by_symbol = {}
            for _sym in symbols[:8]:
                try:
                    news_ctx, news_trace = stonks_agents.SUPERVISOR.news.context(_sym, stonks_news.get_context)
                    news_by_symbol[_sym] = news_ctx
                    agent_trace.append(news_trace)
                except Exception as _news_exc:
                    agent_trace.append({'agent':'news_sentiment','status':'idle','detail':f'{_sym}: noticias no disponibles', 'data':{'error':str(_news_exc)[:240]}, 'timestamp':datetime.now(timezone.utc).isoformat()})
            lifecycle, position_trace = stonks_agents.SUPERVISOR.positions.run(
                scope_id, recon, clock, _stonks_manage_positions)
            agent_trace.append(position_trace)
            d = _stonks_read()
            risk_ok, risk_trace = stonks_agents.SUPERVISOR.risk.precheck(d, clock)
            agent_trace.append(risk_trace)
            shadow_mode = d.get('execution_mode') == 'shadow'
            if shadow_mode:
                shadow_reasons=[]
                if d.get('revoked'): shadow_reasons.append('Control revocado')
                if d.get('paused'): shadow_reasons.append('Motor pausado')
                if d.get('mode')!='paper': shadow_reasons.append('Modo no Paper')
                if not d.get('autonomous_engine'): shadow_reasons.append('Motor autónomo desactivado')
                if not bool(clock.get('is_open')): shadow_reasons.append('Mercado cerrado')
                reason='; '.join(shadow_reasons)
            else:
                reason = stonks_lifecycle.blocked({**d, 'position_lifecycle_enabled':True}, clock)
            if reason:
                _cycle_now = datetime.now(timezone.utc).isoformat()
                d['engine_last_run'] = _cycle_now
                d['engine_last_action'] = ('SHADOW · ' if shadow_mode else '') + reason
                d['agent_last_trace'] = agent_trace[-30:]
                if shadow_mode:
                    d['shadow_cycle_total'] = int(d.get('shadow_cycle_total') or 0) + 1
                    d['shadow_last_cycle'] = _cycle_now
                    d['shadow_last_reason'] = reason
                    d['shadow_last_market_open'] = bool(clock.get('is_open'))
                    d['shadow_last_signal_count'] = 0
                _stonks_write(d)
                return {'status':'idle', 'reason':reason, 'shadow':shadow_mode}
            open_symbols = {o['symbol'] for o in recon['open_orders']}
            held_symbols = {p['symbol'] for p in recon['positions']}
            records = {r['symbol']:r for r in stonks_lifecycle.active_records(d)}
            open_symbols.update(symbol for symbol in records if symbol not in held_symbols)
            open_symbols.update(d.get('pending_entries', {}))
            actions = list(lifecycle.get('actions') or [])
            shadow_actionable_count = 0
            shadow_wait_count = 0
            for symbol in symbols[:8]:
                if symbol in open_symbols:
                    actions.append(f"{symbol}: ORDEN ABIERTA · esperando confirmación de Alpaca")
                    continue
                try:
                    if symbol in held_symbols and symbol not in records:
                        actions.append(symbol + ': posición manual; sin gestión automática')
                        continue
                    signal, analysis_trace = stonks_agents.SUPERVISOR.analysis.signal(
                        symbol, strategy, timeframe, _stonks_current_signal)
                    agent_trace.append(analysis_trace)
                    if symbol in held_symbols:
                        # Preserve strategy SELL exits for owned LONGs, through the same
                        # durable close/Risk state machine (also when SL/TP is disabled).
                        record = records[symbol]
                        if record.get('purpose')=='TEST_LIFECYCLE':
                            continue
                        if signal.get('signal') == 'SELL' and record['side'] == 'buy':
                            latest = _stonks_read()
                            owned = latest['position_ledger'][record['client_order_id']]
                            if not owned.get('trigger'):
                                owned['trigger'] = 'SIGNAL'
                                _stonks_write(latest)
                                _stonks_audit_append('SIGNAL_TRIGGERED', {'symbol':symbol, 'reason':'Salida por estrategia'})
                            result = _stonks_manage_positions(scope_id, _stonks_reconcile_paper_state(scope_id), clock)
                            actions.extend(result.get('actions') or [])
                        continue
                    if signal.get('signal') not in ('BUY','SELL'):
                        if shadow_mode:
                            shadow_wait_count += 1
                        actions.append(f"{symbol}: ESPERAR")
                        continue
                    # Shadow mode evaluates the hardened Decision + Risk route but never submits an order.
                    if shadow_mode:
                        shadow_actionable_count += 1
                        with app.test_request_context('/api/stonks/decision', method='POST', json={
                            'symbol':symbol,'strategy':strategy,'timeframe':timeframe,
                            'signal':signal.get('signal'),'execute':False,'manual_confirmed':False
                        }):
                            session['zar_user_id']=scope_id
                            _shadow_result=stonks_decision_api(engine=True)
                        _shadow_payload=_shadow_result[0] if isinstance(_shadow_result,tuple) else _shadow_result
                        _shadow_data=_shadow_payload.get_json() if hasattr(_shadow_payload,'get_json') else {}
                        _event={
                            'timestamp':datetime.now(timezone.utc).isoformat(),'symbol':symbol,'strategy':strategy,
                            'timeframe':timeframe,'signal':signal.get('signal'),'decision':_shadow_data.get('decision'),
                            'primary_reason':_shadow_data.get('primary_reason') or _shadow_data.get('reason'),
                            'price':_shadow_data.get('price'),'estimated_value':_shadow_data.get('estimated_value'),
                            'order_created':False
                        }
                        latest=_stonks_read(); log=list(latest.get('shadow_log') or []); log.append(_event); latest['shadow_log']=log[-200:]
                        latest['shadow_last_run']=_event['timestamp']; latest['shadow_total_signals']=int(latest.get('shadow_total_signals') or 0)+1
                        _stonks_write(latest); _stonks_audit_append('SHADOW_SIGNAL',_event)
                        agent_trace.append({'agent':'shadow_validation','status':'observed','detail':f"{symbol}: {signal.get('signal')} · {_event.get('decision') or 'sin decisión'} · 0 órdenes",'data':_event,'timestamp':_event['timestamp']})
                        actions.append(f"{symbol}: SHADOW {signal.get('signal')} · {_event.get('decision') or 'sin acción'} · 0 órdenes")
                        continue
                    # Reuse the hardened Decision + Risk route so the autonomous Paper path
                    # has exactly the same server-side gates as manual/GUI execution.
                    def _agent_decision(sym, strat, tf, sig):
                        with app.test_request_context('/api/stonks/decision', method='POST', json={
                            'symbol':sym,'strategy':strat,'timeframe':tf,
                            'signal':sig,'execute':True,'manual_confirmed':False
                        }):
                            session['zar_user_id']=scope_id
                            result=stonks_decision_api(engine=True)
                        payload=result[0] if isinstance(result,tuple) else result
                        return payload.get_json() if hasattr(payload,'get_json') else {}
                    data, execution_trace = stonks_agents.SUPERVISOR.execution.execute(
                        symbol, strategy, timeframe, signal.get('signal'), _agent_decision)
                    agent_trace.append(execution_trace)
                    if data.get('order_created'):
                        order=data.get('order') or {}
                        actions.append(f"{symbol}: {signal.get('signal')} · ORDEN {order.get('status','enviada')} · {order.get('id','—')}")
                    else:
                        actions.append(f"{symbol}: {signal.get('signal')} · {data.get('primary_reason') or data.get('reason') or data.get('decision') or 'sin acción'}")
                except Exception as exc:
                    actions.append(f"{symbol}: ERROR · {exc}")
            recon2, _clock2, market_trace2 = stonks_agents.SUPERVISOR.market.snapshot(
                scope_id, _stonks_reconcile_paper_state, lambda: _alpaca_paper_request('/v2/clock'))
            agent_trace.append(market_trace2)
            lifecycle2, position_trace2 = stonks_agents.SUPERVISOR.positions.run(
                scope_id, recon2, clock, _stonks_manage_positions)
            agent_trace.append(position_trace2)
            actions.extend(lifecycle2.get('actions') or [])
            action=' | '.join(actions)[:2000] if actions else 'Sin señales.'
            d=_stonks_read(); _cycle_now=datetime.now(timezone.utc).isoformat(); d['engine_last_run']=_cycle_now; d['engine_last_action']=action; d['agent_last_trace']=agent_trace[-30:]
            if shadow_mode:
                d['shadow_cycle_total'] = int(d.get('shadow_cycle_total') or 0) + 1
                d['shadow_last_cycle'] = _cycle_now
                d['shadow_last_market_open'] = bool(clock.get('is_open'))
                d['shadow_last_signal_count'] = int(shadow_actionable_count)
                d['shadow_last_reason'] = f"Escaneo completado · {shadow_actionable_count} BUY/SELL · {shadow_wait_count} ESPERAR"
            _stonks_write(d)
            return {'status':'ok','action':action,'shadow':shadow_mode}
        except Exception as exc:
            d=_stonks_read(); _cycle_now=datetime.now(timezone.utc).isoformat(); d['paper_connected']=False; d['engine_last_run']=_cycle_now; d['engine_last_action']='ERROR · reconciliación Paper no disponible; sin órdenes'
            if d.get('execution_mode') == 'shadow':
                d['shadow_cycle_total'] = int(d.get('shadow_cycle_total') or 0) + 1
                d['shadow_last_cycle'] = _cycle_now
                d['shadow_last_reason'] = 'ERROR · reconciliación Paper no disponible; 0 órdenes'
                d['shadow_last_signal_count'] = 0
            _stonks_write(d)
            for record in stonks_lifecycle.active_records(d):
                stonks_lifecycle.test_event(record, 'TEST_LIFECYCLE_ERROR', _stonks_audit_append, 'Alpaca no disponible; conservando intención y ownership')
            for row in d.get('managed_positions', {}).values():
                if row.get('status') != 'CERRADA':
                    row.update(status='ERROR', reason='Snapshot Paper no disponible; conservando último estado')
            _stonks_write(d)
            _stonks_audit_append('POSITION_ERROR', {'reason':'Reconciliación Paper no disponible; sin órdenes'})
            return {'status':'error','reason':'Reconciliación Paper no disponible'}

def _stonks_engine_loop():
    """Single-process-safe Paper worker. A filesystem flock prevents duplicate Gunicorn workers."""
    try:
        import fcntl
    except Exception:
        return
    lock_path=_STONKS_DIR / 'engine.lock'
    lock_path.parent.mkdir(parents=True,exist_ok=True)
    fh=None
    try:
        fh=open(lock_path,'a+')
        fcntl.flock(fh,fcntl.LOCK_EX)
    except Exception:
        try:
            if fh: fh.close()
        except Exception: pass
        return
    while True:
        try:
            owner=_stonks_engine_owner_read()
            if owner:
                _stonks_engine_cycle(owner)
        except Exception:
            pass
        # The autonomous worker is intentionally persistent and independent of the
        # Stonks browser window.  Five seconds gives the engine continuous
        # near-real-time supervision without turning it into a tight CPU loop.
        # It can be tuned from Railway with ZAR_STONKS_ENGINE_INTERVAL.
        try:
            interval=max(2.0,float(os.environ.get('ZAR_STONKS_ENGINE_INTERVAL','5')))
        except Exception:
            interval=5.0
        time.sleep(interval)

@app.get('/api/stonks/status')
def stonks_status_api():
    d=_stonks_read()
    pk,ps=_alpaca_paper_credentials()
    return jsonify({'ok':True, **d, 'lifecycle_test':stonks_lifecycle.test_view(d), 'engine_owner':_stonks_engine_owner_read(), 'engine_owned_by_current_user':_stonks_engine_owner_read()==_user_scope_id(), 'audit_count':len(_stonks_audit_read(200)), 'paper_configured': bool(pk and ps), 'crypto_configured': bool(os.environ.get('KRAKEN_API_KEY') and os.environ.get('KRAKEN_API_SECRET')), 'engine_position_count':len(d.get('engine_last_positions') or []), 'engine_open_order_count':len(d.get('engine_last_open_orders') or []), 'position_lifecycle_enabled':bool(d.get('position_lifecycle_enabled')), 'stop_loss_pct':d.get('stop_loss_pct',1.0), 'take_profit_pct':d.get('take_profit_pct',2.0), 'managed_position_count':sum(r.get('status')!='CERRADA' for r in (d.get('managed_positions') or {}).values()), 'lifecycle_last_action':d.get('lifecycle_last_action'), 'agents':stonks_agents.describe()})

@app.get('/api/stonks/agents')
def stonks_agents_api():
    d=_stonks_read()
    return jsonify({'ok':True,'paper':True, **stonks_agents.describe(), 'last_trace':d.get('agent_last_trace') or []})

@app.get('/api/stonks/news')
def stonks_news_api():
    symbol=re.sub(r'[^A-Za-z0-9.\-]', '', request.args.get('symbol','AAPL').upper())[:16]
    force=request.args.get('force','0') in ('1','true','yes')
    data=stonks_news.get_context(symbol, force=force)
    return jsonify(data)

@app.get('/api/subagents/state')
def subagents_state_api():
    base=subagent_orchestrator.describe_general_agents()
    d=_stonks_read()
    st=stonks_agents.describe()
    # Attach Stonks specialists to the global graph without moving their UI into Stonks.
    financial=[]
    for a in st.get('agents') or []:
        aid='stonks_'+str(a.get('id'))
        financial.append({
            'id':aid,'name':str(a.get('id','agent')).replace('_',' ').title(),
            'icon':'↗' if a.get('id')=='supervisor' else '◇',
            'domain':'finance','role':a.get('role',''),'status':'ready'
        })
    seen={a['id'] for a in base['agents']}
    for a in financial:
        if a['id'] not in seen: base['agents'].append(a)
    for a in financial:
        if a['id']!='stonks_supervisor': base['edges'].append(['stonks_supervisor',a['id']])
    base.update({
        'ok':True,
        'stonks_trace':d.get('agent_last_trace') or [],
        'stonks_phase':st.get('phase'),
        'stonks_paper_only':True,
        'active_count':len([x for x in (d.get('agent_last_trace') or [])[-10:] if x.get('status') not in ('idle','no_action')]),
    })
    return jsonify(base)

@app.post('/api/stonks/alpaca/test')
@_stonks_serialized
def stonks_alpaca_test_api():
    try:
        account=_alpaca_paper_request('/v2/account')
        d=_stonks_read(); d['revoked']=False; d['paused']=True; d['mode']='paper'; _stonks_write(d)
        return jsonify({'ok':True,'paper':True,'authorized':True,'account':{
            'status':account.get('status'),'currency':account.get('currency'),'cash':account.get('cash'),
            'buying_power':account.get('buying_power'),'equity':account.get('equity'),'portfolio_value':account.get('portfolio_value'),
            'account_number':account.get('account_number')
        }})
    except Exception as exc:
        return jsonify({'ok':False,'paper':True,'error':str(exc)}), 502

@app.get('/api/stonks/alpaca/quote')
def stonks_alpaca_quote_api():
    symbol=(request.args.get('symbol') or 'AAPL').strip().upper()
    if not symbol or len(symbol)>20 or not symbol.replace('.','').replace('-','').isalnum():
        return jsonify({'ok':False,'error':'Símbolo no válido.'}),400
    try:
        # The trading clock is deliberately queried from the Paper trading API.
        # This lets the UI distinguish a closed market from an authentication or
        # market-data problem instead of presenting every empty quote as an error.
        clock=_alpaca_paper_request('/v2/clock')
        is_open=bool(clock.get('is_open'))

        quote=None
        trade=None
        snapshot=None
        quote_error=None
        trade_error=None
        snapshot_error=None

        try:
            q=_alpaca_market_request(f'/v2/stocks/{symbol}/quotes/latest')
            quote=(q.get('quotes') or {}).get(symbol)
        except Exception as exc:
            quote_error=str(exc)

        # Outside regular hours the latest quote can be empty depending on the
        # entitled feed. Fall back to latest trade and then snapshot so ZAR can
        # still show the most recent available market information.
        if not quote:
            try:
                t=_alpaca_market_request(f'/v2/stocks/{symbol}/trades/latest')
                trade=(t.get('trades') or {}).get(symbol)
            except Exception as exc:
                trade_error=str(exc)

        if not quote and not trade:
            try:
                snapshot=_alpaca_market_request(f'/v2/stocks/{symbol}/snapshot')
            except Exception as exc:
                snapshot_error=str(exc)

        latest_trade=trade or (snapshot or {}).get('latestTrade')
        latest_quote=quote or (snapshot or {}).get('latestQuote')
        daily_bar=(snapshot or {}).get('dailyBar')

        return jsonify({
            'ok':True,
            'symbol':symbol,
            'market':{
                'is_open':is_open,
                'timestamp':clock.get('timestamp'),
                'next_open':clock.get('next_open'),
                'next_close':clock.get('next_close'),
            },
            'quote':latest_quote,
            'trade':latest_trade,
            'daily_bar':daily_bar,
            'source':'quote' if quote else ('trade' if trade else ('snapshot' if snapshot else None)),
            'diagnostics':{
                'quote_error':quote_error,
                'trade_error':trade_error,
                'snapshot_error':snapshot_error,
            }
        })
    except Exception as exc:
        return jsonify({'ok':False,'error':str(exc)}),502




def _stonks_sma(values, period):
    out=[None]*len(values)
    if period <= 0:
        return out
    total=0.0
    for i,v in enumerate(values):
        total += float(v)
        if i >= period:
            total -= float(values[i-period])
        if i >= period-1:
            out[i]=total/period
    return out


def _stonks_atr(bars, period=14):
    trs=[]
    prev=None
    for b in bars:
        h=float(b.get('h') or 0); l=float(b.get('l') or 0); c=float(b.get('c') or 0)
        tr=max(h-l, abs(h-prev) if prev is not None else 0, abs(l-prev) if prev is not None else 0)
        trs.append(tr); prev=c
    return _stonks_sma(trs, period)


def _stonks_rsi(closes, period=14):
    out=[None]*len(closes)
    if len(closes) <= period:
        return out
    gains=[0.0]*len(closes); losses=[0.0]*len(closes)
    for i in range(1,len(closes)):
        d=float(closes[i])-float(closes[i-1])
        gains[i]=max(d,0.0); losses[i]=max(-d,0.0)
    avg_gain=sum(gains[1:period+1])/period
    avg_loss=sum(losses[1:period+1])/period
    out[period]=100.0 if avg_loss == 0 else 100-(100/(1+(avg_gain/avg_loss)))
    for i in range(period+1,len(closes)):
        avg_gain=((avg_gain*(period-1))+gains[i])/period
        avg_loss=((avg_loss*(period-1))+losses[i])/period
        out[i]=100.0 if avg_loss == 0 else 100-(100/(1+(avg_gain/avg_loss)))
    return out


def _stonks_max_drawdown(equity_curve):
    peak=None; max_dd=0.0
    for value in equity_curve:
        value=float(value)
        peak=value if peak is None else max(peak,value)
        if peak:
            max_dd=min(max_dd,(value-peak)/peak)
    return max_dd



def _stonks_current_signal(symbol, strategy='trend', timeframe='1Min', feed='iex'):
    symbol=str(symbol or 'AAPL').strip().upper()
    timeframe=str(timeframe or '1Min').strip()
    strategy=str(strategy or 'trend').strip().lower()
    feed=str(feed or 'iex').strip().lower()
    if timeframe not in ('1Min','5Min','15Min'):
        timeframe='1Min'
    if strategy not in ('trend','mean_reversion'):
        strategy='trend'
    if feed not in ('iex','sip'):
        feed='iex'
    clock=_alpaca_paper_request('/v2/clock')
    end=datetime.now(timezone.utc)
    from datetime import timedelta
    start=end-timedelta(hours=8 if timeframe=='1Min' else 24)
    params={
        'symbols':symbol,'timeframe':timeframe,
        'start':start.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'end':end.strftime('%Y-%m-%dT%H:%M:%SZ'),'limit':1000,
        'feed':feed,'sort':'asc'
    }
    data=_alpaca_market_request('/v2/stocks/bars',params=params)
    raw=(data.get('bars') or {}).get(symbol) if isinstance(data,dict) else []
    raw=raw if isinstance(raw,list) else []
    current_minute=end.replace(second=0,microsecond=0)
    bars=[]
    for b in raw:
        try:
            ts=datetime.fromisoformat(str(b.get('t','')).replace('Z','+00:00'))
            if ts >= current_minute: continue
            if all(k in b for k in ('o','h','l','c')): bars.append(b)
        except Exception:
            continue
    bars=bars[-120:]
    closes=[float(b['c']) for b in bars]
    item={'symbol':symbol,'timeframe':timeframe,'strategy':strategy,'signal':'HOLD','signal_label':'ESPERAR',
          'reason':'Sin cruce nuevo confirmado en la última barra cerrada.','price':closes[-1] if closes else None,
          'bar_time':bars[-1].get('t') if bars else None,'bars':len(bars),'indicators':{}}
    if len(bars)<55:
        item['signal_label']='SIN DATOS'; item['reason']=f'Se necesitan al menos 55 barras cerradas; disponibles: {len(bars)}.'
    elif strategy=='trend':
        sma20=_stonks_sma(closes,20); sma50=_stonks_sma(closes,50)
        p20,p50=sma20[-2],sma50[-2]; c20,c50=sma20[-1],sma50[-1]
        rsi=_stonks_rsi(closes,14); atr=_stonks_atr(bars,14)
        cr=rsi[-1] if rsi else None; ca=atr[-1] if atr else None
        atr_pct=(float(ca)/max(abs(closes[-1]),1e-9)*100.0) if ca is not None else None
        gap_pct=abs(c20-c50)/max(abs(c50),1e-9)*100.0
        if atr_pct is not None and atr_pct >= 1.5:
            regime='alta_volatilidad'
        elif gap_pct >= 0.35:
            regime='tendencia_alcista' if c20>c50 else 'tendencia_bajista'
        else:
            regime='lateral'
        item['indicators']={'sma20':round(c20,4),'sma50':round(c50,4),
            'rsi14':round(cr,2) if cr is not None else None,
            'atr14':round(ca,4) if ca is not None else None,
            'atr_pct':round(atr_pct,3) if atr_pct is not None else None,
            'regime':regime}
        if p20 is not None and p50 is not None and p20 <= p50 and c20 > c50:
            item['signal']='BUY'; item['signal_label']='COMPRA'; item['reason']=f'SMA20 ({c20:.2f}) cruzó al alza SMA50 ({c50:.2f}) en la última barra cerrada.'
        elif p20 is not None and p50 is not None and p20 >= p50 and c20 < c50:
            item['signal']='SELL'; item['signal_label']='VENTA'; item['reason']=f'SMA20 ({c20:.2f}) cruzó a la baja SMA50 ({c50:.2f}) en la última barra cerrada.'
        else:
            relation='por encima' if c20>c50 else ('por debajo' if c20<c50 else 'igual a')
            item['reason']=f'SMA20 ({c20:.2f}) está {relation} de SMA50 ({c50:.2f}); no hay cruce nuevo.'
    else:
        rsi=_stonks_rsi(closes,14); pr,cr=rsi[-2],rsi[-1]
        atr=_stonks_atr(bars,14); ca=atr[-1] if atr else None
        atr_pct=(float(ca)/max(abs(closes[-1]),1e-9)*100.0) if ca is not None else None
        regime='alta_volatilidad' if atr_pct is not None and atr_pct >= 1.5 else ('sobreventa' if cr<30 else ('sobrecompra' if cr>70 else 'lateral'))
        item['indicators']={'rsi14':round(cr,2),
            'atr14':round(ca,4) if ca is not None else None,
            'atr_pct':round(atr_pct,3) if atr_pct is not None else None,
            'regime':regime}
        if pr is not None and pr >= 30 and cr < 30:
            item['signal']='BUY'; item['signal_label']='COMPRA'; item['reason']=f'RSI14 cayó por debajo de 30 ({cr:.2f}) en la última barra cerrada.'
        elif pr is not None and pr <= 70 and cr > 70:
            item['signal']='SELL'; item['signal_label']='VENTA'; item['reason']=f'RSI14 superó 70 ({cr:.2f}) en la última barra cerrada.'
        else:
            zone='sobreventa' if cr<30 else ('sobrecompra' if cr>70 else 'zona neutral')
            item['reason']=f'RSI14 = {cr:.2f} ({zone}); no hay cruce nuevo.'
    return item, clock

@app.get('/api/stonks/signals')
def stonks_signals_api():
    """Calculate near-real-time signals from completed Alpaca bars. Analysis only."""
    try:
        raw_symbols=str(request.args.get('symbols') or 'AAPL')
        symbols=[]
        for raw in raw_symbols.split(','):
            symbol=raw.strip().upper()
            if symbol and symbol not in symbols: symbols.append(symbol)
        if not symbols: symbols=['AAPL']
        if len(symbols)>8: return jsonify({'ok':False,'error':'Máximo 8 símbolos por análisis.'}),400
        for symbol in symbols:
            if len(symbol)>20 or not symbol.replace('.','').replace('-','').isalnum():
                return jsonify({'ok':False,'error':f'Símbolo no válido: {symbol}.'}),400
        timeframe=request.args.get('timeframe','1Min')
        strategy=request.args.get('strategy','trend')
        feed=request.args.get('feed','iex')
        results=[]; clock=None
        for symbol in symbols:
            item,clock=_stonks_current_signal(symbol,strategy,timeframe,feed)
            results.append(item)
        return jsonify({'ok':True,'analysis_only':True,'orders_created':False,'paper':True,
            'strategy':str(strategy),'timeframe':str(timeframe),'feed':str(feed),
            'market':{'is_open':bool(clock.get('is_open')),'timestamp':clock.get('timestamp'),'next_open':clock.get('next_open'),'next_close':clock.get('next_close')},
            'generated_at':datetime.now(timezone.utc).isoformat(),'signals':results})
    except Exception as exc:
        return jsonify({'ok':False,'error':str(exc)}),502

@app.post('/api/stonks/test-cycle')
@_stonks_serialized
def stonks_test_cycle_api():
    """Run one explicit, server-side Paper test order through the Risk gates.
    This is a synthetic test and is never treated as a market signal.
    """
    try:
        payload=request.get_json(silent=True) or {}
        if not bool(payload.get('confirm')):
            return jsonify({'ok':False,'error':'La prueba Paper requiere confirmación explícita.'}),400
        symbol=str(payload.get('symbol') or 'AAPL').strip().upper()
        if not symbol or len(symbol)>20 or not symbol.replace('.','').replace('-','').isalnum():
            return jsonify({'ok':False,'error':'Símbolo no válido.'}),400
        d=_stonks_read()
        if d.get('revoked'):
            return jsonify({'ok':True,'paper':True,'order_created':False,'decision':'DENEGADA','primary_reason':'Control revocado.'})
        if d.get('paused'):
            return jsonify({'ok':True,'paper':True,'order_created':False,'decision':'DENEGADA','primary_reason':'Motor pausado.'})
        if d.get('mode')!='paper':
            return jsonify({'ok':True,'paper':True,'order_created':False,'decision':'DENEGADA','primary_reason':'El modo operativo no es Paper.'})
        if d.get('execution_mode')!='paper_auto':
            return jsonify({'ok':True,'paper':True,'order_created':False,'decision':'DENEGADA','primary_reason':'Activa Paper automático · con Risk antes de ejecutar la prueba.'})
        clock=_alpaca_paper_request('/v2/clock')
        if not bool(clock.get('is_open')):
            reason='Mercado cerrado.'
            _stonks_audit_append('TEST_PAPER',{'symbol':symbol,'decision':'DENEGADA','primary_reason':reason})
            return jsonify({'ok':True,'paper':True,'order_created':False,'decision':'DENEGADA','primary_reason':reason})

        account=_alpaca_paper_request('/v2/account')
        equity=float(account.get('equity') or 0)
        last_equity=float(account.get('last_equity') or 0)
        daily_loss=max(0.0,last_equity-equity)
        max_daily=float(d.get('max_daily_loss_eur',10))
        if daily_loss>=max_daily:
            reason=f'Pérdida diaria límite alcanzada: {daily_loss:.2f} USD / límite {max_daily:.2f} USD.'
            _stonks_audit_append('TEST_PAPER',{'symbol':symbol,'decision':'DENEGADA','primary_reason':reason})
            return jsonify({'ok':True,'paper':True,'order_created':False,'decision':'DENEGADA','primary_reason':reason})

        latest=_alpaca_market_request(f'/v2/stocks/{symbol}/trades/latest', params={'feed':'iex'})
        last=(latest.get('trade') or {}) if isinstance(latest,dict) else {}
        if not last and isinstance(latest,dict):
            last=(latest.get('trades') or {}).get(symbol) or {}
        price=float(last.get('p') or 0)
        if price<=0:
            reason='Precio actual no disponible.'
            _stonks_audit_append('TEST_PAPER',{'symbol':symbol,'decision':'DENEGADA','primary_reason':reason})
            return jsonify({'ok':True,'paper':True,'order_created':False,'decision':'DENEGADA','primary_reason':reason})

        positions=_alpaca_paper_request('/v2/positions')
        positions=positions if isinstance(positions,list) else []
        current=next((p for p in positions if str(p.get('symbol','')).upper()==symbol),None)
        current_value=abs(float((current or {}).get('market_value') or 0))
        max_trade=float(d.get('max_trade_eur',25))
        max_position=float(d.get('max_position_pct',20))
        position_cap=max(0.0,equity*(max_position/100.0)-current_value)
        test_value=min(1.01,max_trade,position_cap)
        if test_value<1.0:
            reason=f'No hay margen suficiente para la prueba mínima de 1,00 USD: disponible {test_value:.2f} USD.'
            _stonks_audit_append('TEST_PAPER',{'symbol':symbol,'decision':'DENEGADA','primary_reason':reason})
            return jsonify({'ok':True,'paper':True,'order_created':False,'decision':'DENEGADA','primary_reason':reason})
        import math
        qty=math.ceil((test_value/price)*1_000_000_000)/1_000_000_000
        qty=float(f'{qty:.9f}')
        order_value=qty*price
        if order_value>max_trade+1e-9 or current_value+order_value>equity*(max_position/100.0)+1e-9:
            reason='La prueba supera uno de los límites Risk configurados.'
            _stonks_audit_append('TEST_PAPER',{'symbol':symbol,'decision':'DENEGADA','primary_reason':reason,'qty':qty,'estimated_value':order_value})
            return jsonify({'ok':True,'paper':True,'order_created':False,'decision':'DENEGADA','primary_reason':reason})

        body={'symbol':symbol,'qty':str(qty),'side':'buy','type':'market','time_in_force':'day'}
        key_api,secret_api=_alpaca_paper_credentials()
        rr=requests.post('https://paper-api.alpaca.markets/v2/orders',headers={'APCA-API-KEY-ID':key_api,'APCA-API-SECRET-KEY':secret_api,'Accept':'application/json','Content-Type':'application/json'},json=body,timeout=12)
        try: order=rr.json()
        except Exception: order={'raw':rr.text[:1000]}
        if not rr.ok:
            error=order.get('message') if isinstance(order,dict) else 'orden rechazada'
            _stonks_audit_append('TEST_PAPER',{'symbol':symbol,'decision':'RECHAZADA_POR_ALPACA','error':error,'qty':qty,'estimated_value':order_value})
            return jsonify({'ok':False,'paper':True,'order_created':False,'error':error}),502
        _stonks_audit_append('TEST_PAPER',{'symbol':symbol,'decision':'ORDEN_ENVIADA','side':'buy','qty':qty,'estimated_value':order_value,'order_id':order.get('id'),'status':order.get('status')})
        return jsonify({'ok':True,'paper':True,'order_created':True,'test':True,'symbol':symbol,'qty':qty,'estimated_value':order_value,'order':order})
    except Exception as exc:
        return jsonify({'ok':False,'paper':True,'error':str(exc)}),502

@app.get('/api/stonks/audit')
def stonks_audit_api():
    return jsonify({'ok':True,'paper':True,'audit':list(reversed(_stonks_audit_read(100)))})

@app.post('/api/stonks/decision')
@_stonks_serialized
def stonks_decision_api(engine=False, lifecycle_test=False):
    """Evaluate one current signal against ZAR Risk and optionally execute Paper.
    Live trading is intentionally impossible in this endpoint."""
    try:
        payload=request.get_json(silent=True) or {}
        symbol=str(payload.get('symbol') or '').strip().upper()
        strategy=str(payload.get('strategy') or 'trend').strip().lower()
        timeframe=str(payload.get('timeframe') or '1Min').strip()
        requested_signal=str(payload.get('signal') or '').strip().upper()
        execute=bool(payload.get('execute'))
        manual_confirmed=bool(payload.get('manual_confirmed'))
        if not symbol or len(symbol)>20 or not symbol.replace('.','').replace('-','').isalnum():
            return jsonify({'ok':False,'error':'Símbolo no válido.'}),400
        if requested_signal not in ('BUY','SELL'):
            return jsonify({'ok':True,'paper':True,'decision':'NO_ACTION','reason':'La señal actual no requiere una operación.','order_created':False})
        if lifecycle_test:
            # Internal-only synthetic decision source; every production Risk check below still applies.
            engine = True
            strategy = 'TEST_LIFECYCLE'
            requested_signal = 'BUY'
            execute = True
            actual = {'signal':'BUY', 'bar_time':'TEST:'+str(payload.get('request_id'))}
            clock = _alpaca_paper_request('/v2/clock')
        else:
            actual,clock=_stonks_current_signal(symbol,strategy,timeframe,'iex')
        if actual.get('signal') != requested_signal:
            _stonks_audit_append('DECISIÓN',{'symbol':symbol,'requested_signal':requested_signal,'actual_signal':actual.get('signal'),'decision':'DENEGADA','reason':'La señal enviada ya no coincide con la última barra cerrada.'})
            return jsonify({'ok':True,'paper':True,'decision':'DENEGADA','reason':'La señal enviada ya no coincide con la última barra cerrada.','current_signal':actual,'order_created':False})
        d=_stonks_read()
        reasons=[]
        checks=[]
        def add_check(code, label, passed, detail=''):
            checks.append({'code':code,'label':label,'passed':bool(passed),'detail':detail})
            if not passed and label:
                reasons.append(label + (f': {detail}' if detail else ''))

        # Kill-switch / operating-state checks are evaluated first and remain authoritative.
        add_check('REVOKED','Control revocado',not bool(d.get('revoked')))
        add_check('PAUSED','Motor pausado',not bool(d.get('paused')))
        add_check('MODE','Modo distinto de Paper',d.get('mode')=='paper')
        add_check('MARKET','Mercado cerrado',bool(clock.get('is_open')))
        if lifecycle_test:
            add_check('LIFECYCLE', 'Gestión de posición desactivada', bool(d.get('position_lifecycle_enabled')))
            add_check('AUTO', 'Modo Paper automático requerido', d.get('execution_mode')=='paper_auto')
            add_check('SINGLE_TEST', 'Ya existe una prueba activa', not any(r.get('purpose')=='TEST_LIFECYCLE' for r in stonks_lifecycle.active_records(d)))


        account=_alpaca_paper_request('/v2/account')
        equity=float(account.get('equity') or 0); last_equity=float(account.get('last_equity') or 0)
        if lifecycle_test:
            equity = float(stonks_lifecycle.number(account.get('equity')))
            last_equity = float(stonks_lifecycle.number(account.get('last_equity')))
            for field in ['max_trade_eur','max_position_pct','max_daily_loss_eur']:
                stonks_lifecycle.number(d[field])
            add_check('EQUITY', 'Capital Paper no válido para una prueba', equity>0)
            add_check('CONNECTED', 'Alpaca Paper no está disponible para operar', account.get('status')=='ACTIVE' and not (account.get('trading_blocked') or account.get('account_blocked')))
            add_check('BUYING_POWER', 'Saldo Paper insuficiente para 1 USD', float(account.get('buying_power') or 0)>=1)
            asset = _alpaca_paper_request('/v2/assets/'+symbol)
            add_check('FRACTIONABLE', 'Activo no compatible con prueba mínima Paper', asset.get('status')=='active' and asset.get('tradable') is True and asset.get('fractionable') is True and asset.get('class')=='us_equity')

        daily_loss=max(0.0,last_equity-equity); max_daily=float(d.get('max_daily_loss_eur',10))
        add_check('DAILY_LOSS','Pérdida diaria límite alcanzada',not (daily_loss>=max_daily),f'{daily_loss:.2f} USD / límite {max_daily:.2f} USD')

        positions=_alpaca_paper_request('/v2/positions')
        if not isinstance(positions,list):
            raise RuntimeError('Snapshot de posiciones Paper no válido')
        current=next((p for p in positions if str(p.get('symbol','')).upper()==symbol),None)
        if engine:
            add_check('ENGINE_OWNER', 'Motor no autorizado', d.get('autonomous_engine') and _stonks_engine_owner_read()==_user_scope_id())
            add_check('FLAT_BASELINE', 'El motor solo abre símbolos sin posición previa', current is None)
            add_check('OWNERSHIP_PENDING', 'Hay una intención ZAR pendiente de reconciliar',
                      not any(r['symbol']==symbol for r in stonks_lifecycle.active_records(d)))


        # The single-symbol latest-trade endpoint returns {symbol, trade}; the plural endpoint returns {trades:{SYMBOL:...}}.
        # v31.3.7 accepts both forms so a valid live price cannot be misclassified as unavailable.
        latest=_alpaca_market_request(f'/v2/stocks/{symbol}/trades/latest', params={'feed':'iex'})
        last=(latest.get('trade') or {}) if isinstance(latest,dict) else {}
        if not last and isinstance(latest,dict):
            last=(latest.get('trades') or {}).get(symbol) or {}
        price=float(last.get('p') or 0)
        add_check('PRICE','Precio actual no disponible',price>0)

        max_trade=float(d.get('max_trade_eur',25))
        max_position=float(d.get('max_position_pct',20))
        current_value=abs(float((current or {}).get('market_value') or 0))
        current_qty=float((current or {}).get('qty') or 0)
        if requested_signal=='SELL':
            add_check('POSITION','No existe posición Paper que vender',current_qty>0)
            qty=min(current_qty, max_trade/price if price>0 else 0)
        else:
            available_value=max(0.0,equity*(max_position/100.0)-current_value)
            qty=min(max_trade/price if price>0 else 0, available_value/price if price>0 else 0)
        qty=float(f'{qty:.9f}')
        order_value=qty*price
        if lifecycle_test:
            # Fixed minimal dollar notional avoids quote movement/rounding changing the entry size.
            qty = float(f'{1.0/price:.9f}') if price>0 else 0
            order_value = 1.0


        # Alpaca supports fractional equity orders. For BUY, keep our own 1 USD floor; for SELL, do not
        # invent a notional floor that could prevent closing a small existing Paper position.
        if requested_signal=='BUY':
            add_check('MIN_NOTIONAL','Tamaño BUY inferior al mínimo operativo',qty>0 and order_value>=1.0,f'{order_value:.2f} USD')
        else:
            add_check('QTY','Cantidad SELL no operativa',qty>0,f'{qty:.9f} acciones')
        add_check('MAX_TRADE','Supera el máximo por operación',order_value<=max_trade+1e-9,f'{order_value:.2f} USD / límite {max_trade:.2f} USD')
        if requested_signal=='BUY':
            add_check('MAX_POSITION','Supera el máximo de posición configurado',not (equity>0 and current_value+order_value>equity*(max_position/100.0)+1e-9),f'{current_value+order_value:.2f} USD / límite {equity*(max_position/100.0):.2f} USD')

        try:
            open_orders=_alpaca_paper_request('/v2/orders', params={'status':'open','limit':500,'nested':'false'})
            if not isinstance(open_orders,list) or len(open_orders)>=500:
                raise RuntimeError('Snapshot de órdenes Paper incompleto')
            same_symbol=[o for o in open_orders if str(o.get('symbol') or '').upper()==symbol]
        except Exception as exc:
            same_symbol=[]
            add_check('OPEN_ORDER','No se pudo comprobar órdenes abiertas',False,str(exc))
        else:
            add_check('OPEN_ORDER','Ya existe una orden Paper abierta para este símbolo',not bool(same_symbol),f'{len(same_symbol)} orden(es) abierta(s)')

        key=f'{symbol}|{strategy}|{timeframe}|{actual.get("bar_time")}|{requested_signal}'
        add_check('DUPLICATE','Esta señal ya fue ejecutada',not bool(d.get('last_executed_signals',{}).get(key)))

        approved=not reasons
        decision='APROBADA' if approved else 'DENEGADA'
        primary_reason=reasons[0] if reasons else 'Todos los controles Risk han sido superados.'
        result={'ok':True,'paper':True,'decision':decision,'signal':requested_signal,'symbol':symbol,'strategy':strategy,'timeframe':timeframe,
                'price':price,'qty':qty,'estimated_value':order_value,'reasons':reasons,'primary_reason':primary_reason,'checks':checks,'current_signal':actual,'order_created':False}
        _stonks_audit_append('DECISIÓN',{'symbol':symbol,'signal':requested_signal,'strategy':strategy,'timeframe':timeframe,'decision':decision,'price':price,'qty':qty,'estimated_value':order_value,'primary_reason':primary_reason,'reasons':reasons,'checks':checks})
        if approved and execute:
            if d.get('execution_mode')!='paper_auto' and not manual_confirmed:
                result['decision']='APROBADA_SIN_EJECUTAR'; result['reason']='La ejecución requiere modo Paper automático o confirmación manual explícita.'
                _stonks_audit_append('DECISIÓN',{'symbol':symbol,'signal':requested_signal,'strategy':strategy,'timeframe':timeframe,'decision':'APROBADA_SIN_EJECUTAR','reason':'Falta confirmación manual explícita y Paper automático no está activo.'})
                return jsonify(result)
            if lifecycle_test:
                preflight = _stonks_lifecycle_preflight(symbol)
                if preflight['status']!='READY':
                    return jsonify({'ok':False,'order_created':False,'primary_reason':'Pre-flight Paper no READY','preflight':preflight}),409
            body={'symbol':symbol,'qty':str(qty),'side':'buy' if requested_signal=='BUY' else 'sell','type':'market','time_in_force':'day'}
            if engine:
                intent = stonks_lifecycle.entry_intent(d, symbol, body['side'], qty, strategy, timeframe)
                if lifecycle_test:
                    body.pop('qty')
                    body['notional'] = '1.00'
                    intent.update(purpose='TEST_LIFECYCLE', origin='TEST_LIFECYCLE', test_request_id=payload['request_id'], notional_requested='1.00')
                    _stonks_write(d)
                    stonks_lifecycle.test_event(intent, 'TEST_LIFECYCLE_STARTED', _stonks_audit_append, 'Prueba Paper confirmada; intención persistida', str(qty), price)

                body['client_order_id'] = intent['client_order_id']
                d['last_executed_signals'][key] = datetime.now(timezone.utc).isoformat()
                _stonks_write(d)  # ownership + dedup intent durable BEFORE network
                order = _stonks_submit_paper_order(body)
                intent['order_id'] = order['id']
                if lifecycle_test:
                    stonks_lifecycle.test_event(intent, 'TEST_ENTRY_REQUESTED', _stonks_audit_append, 'Entrada Paper enviada; esperando fill', str(qty), price)
                _stonks_write(d)
                result.update(order_created=True, order=order)
                _stonks_audit_append('ORDEN PAPER', {'symbol':symbol, 'qty':qty, 'price':price,
                    'order_id':order['id'], 'client_order_id':intent['client_order_id'], 'strategy':strategy})
                return jsonify(result)
            key_api,secret_api=_alpaca_paper_credentials()
            rr=requests.post('https://paper-api.alpaca.markets/v2/orders',headers={'APCA-API-KEY-ID':key_api,'APCA-API-SECRET-KEY':secret_api,'Accept':'application/json','Content-Type':'application/json'},json=body,timeout=12)
            try: order=rr.json()
            except Exception: order={'raw':rr.text[:1000]}
            if not rr.ok:
                result['decision']='ERROR_PAPER'; result['order_error']=order.get('message') if isinstance(order,dict) else 'orden rechazada'
                _stonks_audit_append('ORDEN PAPER',{'symbol':symbol,'signal':requested_signal,'decision':'RECHAZADA_POR_ALPACA','error':result['order_error']})
            else:
                d['last_executed_signals'][key]=datetime.now(timezone.utc).isoformat()
                d['execution_mode']='paper_auto' if d.get('execution_mode')=='paper_auto' else d.get('execution_mode','decision')
                _stonks_write(d); result['order_created']=True; result['order']=order
                _stonks_audit_append('ORDEN PAPER',{'symbol':symbol,'signal':requested_signal,'side':body['side'],'qty':qty,'estimated_value':order_value,'order_id':order.get('id'),'status':order.get('status')})
        return jsonify(result)
    except Exception as exc:
        return jsonify({'ok':False,'error':str(exc)}),502

def _stonks_lifecycle_preflight(symbol):
    symbol = str(symbol or '').strip().upper()
    d = _stonks_read()
    key, secret = _alpaca_paper_credentials()
    snapshots = {}
    if key and secret:
        paths = {'account':'/v2/account', 'clock':'/v2/clock', 'positions':'/v2/positions', 'orders':'/v2/orders'}
        if stonks_preflight.valid_symbol(symbol):
            paths['asset'] = '/v2/assets/'+symbol
        for name, path in paths.items():
            try:
                value = _alpaca_paper_request(path, **({'params':{'status':'open','limit':500,'nested':'false'}} if name=='orders' else {}))
                if isinstance(value, list if name in ('positions','orders') else dict):
                    snapshots[name] = value
            except Exception:
                pass  # No broker bodies/secrets in the response; absent evidence is UNVERIFIED.
    return stonks_preflight.evaluate(d, symbol, snapshots, bool(key and secret),
                                     _stonks_engine_owner_read()==_user_scope_id())


@app.get('/api/stonks/lifecycle-test/preflight')
@_stonks_serialized
def stonks_lifecycle_test_preflight_api():
    return jsonify({'ok':True, 'paper':True, 'preflight':_stonks_lifecycle_preflight(request.args.get('symbol','AAPL'))})


def _stonks_test_gate(d):
    reason = stonks_lifecycle.blocked(d, {'is_open':True})
    if reason:
        return reason
    if _stonks_engine_owner_read()!=_user_scope_id():
        return 'La prueba requiere el propietario del motor servidor'
    return ''


@app.post('/api/stonks/lifecycle-test/start')
@_stonks_serialized
def stonks_lifecycle_test_start_api():
    payload = request.get_json(silent=True) or {}
    if payload.get('confirm') is not True:
        return jsonify({'ok':False,'error':'Confirma expresamente la prueba Paper de 1 USD'}),400
    try:
        request_id = str(uuid.UUID(str(payload.get('request_id') or '')))
    except ValueError:
        return jsonify({'ok':False,'error':'Identificador de solicitud no válido'}),400
    d = _stonks_read()
    previous = next((r for r in d['position_ledger'].values() if r.get('test_request_id')==request_id and r.get('purpose')=='TEST_LIFECYCLE'), None)
    if previous:
        return jsonify({'ok':True,'paper':True,'replayed':True,'lifecycle_test':stonks_lifecycle.test_view(d)})
    reason = _stonks_test_gate(d)
    if reason or any(r.get('purpose')=='TEST_LIFECYCLE' for r in stonks_lifecycle.active_records(d)):
        return jsonify({'ok':False,'error':reason or 'Ya existe una prueba Paper activa'}),409
    me = _user_scope_id()
    with app.test_request_context('/api/stonks/decision', method='POST', json={
            'symbol':payload.get('symbol') or (d.get('engine_symbols') or ['AAPL'])[0],
            'request_id':request_id, 'signal':'BUY', 'execute':True}):
        session['zar_user_id']=me
        response = stonks_decision_api(engine=True, lifecycle_test=True)
    response = response[0] if isinstance(response,tuple) else response
    result = response.get_json()
    d = _stonks_read()
    record = next((r for r in d['position_ledger'].values() if r.get('test_request_id')==request_id),None)
    if not result.get('order_created'):
        reason = result.get('primary_reason') or 'Entrada Paper no confirmada; se reconciliará sin duplicar'
        if record:
            stonks_lifecycle.test_event(record, 'TEST_LIFECYCLE_ERROR', _stonks_audit_append, reason)
            _stonks_write(d)
        else:
            _stonks_audit_append('TEST_LIFECYCLE_ERROR', {'reason':reason,'purpose':'TEST_LIFECYCLE'})
        return jsonify({'ok':False,'paper':True,'error':reason,'lifecycle_test':stonks_lifecycle.test_view(d)}),409
    return jsonify({'ok':True,'paper':True,'lifecycle_test':stonks_lifecycle.test_view(d)}),202


@app.post('/api/stonks/lifecycle-test/close')
@_stonks_serialized
def stonks_lifecycle_test_close_api():
    payload = request.get_json(silent=True) or {}
    d = _stonks_read()
    record = d['position_ledger'].get(str(payload.get('id') or ''))
    if payload.get('confirm') is not True or not record or record.get('purpose')!='TEST_LIFECYCLE':
        return jsonify({'ok':False,'error':'Solo se permite cerrar una prueba TEST_LIFECYCLE confirmada'}),400
    if record.get('closed'):
        return jsonify({'ok':True,'paper':True,'lifecycle_test':stonks_lifecycle.test_view(d)})
    reason = _stonks_test_gate(d)
    if reason:
        return jsonify({'ok':False,'error':reason}),409
    row = d['managed_positions'].get(record['symbol'], {})
    if row.get('client_order_id')!=record['client_order_id'] or not row.get('opened_at') or record.get('ownership_conflict') or row.get('status')=='ERROR':
        return jsonify({'ok':False,'error':'La posición de prueba todavía no tiene ownership confirmado o requiere revisión'}),409
    try:
        account = _alpaca_paper_request('/v2/account')
        if account.get('status')!='ACTIVE' or account.get('trading_blocked') or account.get('account_blocked'):
            raise RuntimeError('Paper no disponible')
    except Exception:
        stonks_lifecycle.test_event(record, 'TEST_LIFECYCLE_ERROR', _stonks_audit_append, 'No se pudo verificar la conexión Alpaca Paper')
        _stonks_write(d)
        return jsonify({'ok':False,'error':'No se pudo verificar la conexión Alpaca Paper','lifecycle_test':stonks_lifecycle.test_view(d)}),409
    # Durable request only: the worker reconciles quantity/ownership and applies all exit Risk checks.
    if not record.get('trigger'):
        record['trigger'] = 'TEST'
        record['test_close_requested_at'] = datetime.now(timezone.utc).isoformat()
        _stonks_write(d)
    return jsonify({'ok':True,'paper':True,'lifecycle_test':stonks_lifecycle.test_view(d)}),202


@app.delete('/api/stonks/alpaca/orders')
@_stonks_serialized
def stonks_alpaca_cancel_all_orders_api():
    """Emergency cancellation of all open orders in Alpaca Paper only."""
    try:
        data=_alpaca_paper_request('/v2/orders', method='DELETE')
        _stonks_audit_append('CANCELACIÓN GLOBAL', {'paper':True, 'result':data if isinstance(data,(list,dict)) else str(data)})
        return jsonify({'ok':True,'paper':True,'canceled':data})
    except Exception as exc:
        _stonks_audit_append('CANCELACIÓN GLOBAL', {'paper':True, 'error':str(exc)})
        return jsonify({'ok':False,'paper':True,'error':str(exc)}),502

@app.post('/api/stonks/backtest')
def stonks_backtest_api():
    """Deterministic historical validation. Never creates, modifies or cancels broker orders."""
    try:
        payload=request.get_json(silent=True) or {}
        symbol=str(payload.get('symbol') or 'AAPL').strip().upper()
        strategy=str(payload.get('strategy') or 'trend').strip().lower()
        try: days=int(payload.get('days') or 365)
        except Exception: days=365
        try: capital=float(payload.get('capital') or 10000)
        except Exception: capital=10000
        try: risk_pct=float(payload.get('risk_pct') or 1)
        except Exception: risk_pct=1
        try: slippage_pct=float(payload.get('slippage_pct') or 0.05)
        except Exception: slippage_pct=0.05
        feed=str(payload.get('feed') or 'iex').strip().lower()
        if not symbol or len(symbol)>20 or not symbol.replace('.','').replace('-','').isalnum():
            return jsonify({'ok':False,'error':'Símbolo no válido.'}),400
        if strategy not in ('trend','mean_reversion'):
            return jsonify({'ok':False,'error':'Estrategia no válida.'}),400
        days=max(30,min(days,2000)); capital=max(100.0,min(capital,100000000.0)); risk_pct=max(0.1,min(risk_pct,10.0)); slippage_pct=max(0,min(slippage_pct,2.0))
        if feed not in ('iex','sip'): feed='iex'
        from datetime import timedelta
        end=datetime.now(timezone.utc); start=end-timedelta(days=days)
        params={'timeframe':'1Day','start':start.strftime('%Y-%m-%dT%H:%M:%SZ'),'end':end.strftime('%Y-%m-%dT%H:%M:%SZ'),'limit':10000,'feed':feed,'sort':'asc'}
        data=_alpaca_market_request('/v2/stocks/'+symbol+'/bars',params=params)
        bars=data.get('bars') if isinstance(data,dict) else []
        bars=[b for b in (bars or []) if all(k in b for k in ('o','h','l','c'))]
        if len(bars)<60:
            return jsonify({'ok':False,'error':f'Alpaca no ha devuelto suficientes barras diarias para {symbol} ({len(bars)}).'}),422
        result=stonks_backtest.run_backtest(bars,strategy,capital,risk_pct,slippage_pct)
        curve=result.pop('equity_curve')
        result.update({
            'ok':True,'paper':True,'orders_created':False,'symbol':symbol,'strategy':strategy,'feed':feed,
            'period':{'start':bars[0].get('t'),'end':bars[-1].get('t'),'bars':len(bars)},
            'parameters':{'capital':capital,'risk_pct':risk_pct,'slippage_pct':slippage_pct,'days':days},
            'trades':result.get('trades',[])[-150:],
            'equity_curve':[{'date':bars[i].get('t'),'equity':round(curve[i],2)} for i in range(0,len(curve),max(1,len(curve)//160))]
        })
        return jsonify(result)
    except Exception as exc:
        return jsonify({'ok':False,'error':str(exc)}),502


@app.post('/api/stonks/validation-suite')
def stonks_validation_suite_api():
    """Multi-symbol/multi-period deterministic robustness lab. Never sends broker orders."""
    try:
        payload=request.get_json(silent=True) or {}
        raw_symbols=payload.get('symbols') or ['AAPL','MSFT','SPY','QQQ']
        if isinstance(raw_symbols,str): raw_symbols=[x.strip().upper() for x in raw_symbols.split(',') if x.strip()]
        symbols=[]
        for sym in raw_symbols:
            sym=str(sym).strip().upper()
            if sym and len(sym)<=20 and sym.replace('.','').replace('-','').isalnum() and sym not in symbols:
                symbols.append(sym)
        symbols=symbols[:6]
        if not symbols: return jsonify({'ok':False,'error':'Añade al menos un símbolo válido.'}),400

        raw_periods=payload.get('periods') or [180,365,730]
        if isinstance(raw_periods,str): raw_periods=[x.strip() for x in raw_periods.split(',') if x.strip()]
        periods=[]
        for value in raw_periods:
            try: d=max(90,min(int(value),2000))
            except Exception: continue
            if d not in periods: periods.append(d)
        periods=sorted(periods)[:5]
        if not periods: periods=[180,365,730]

        strategy=str(payload.get('strategy') or 'trend').strip().lower()
        if strategy not in ('trend','mean_reversion'): return jsonify({'ok':False,'error':'Estrategia no válida.'}),400
        try: capital=max(100.0,min(float(payload.get('capital') or 10000),100000000.0))
        except Exception: capital=10000.0
        try: risk_pct=max(0.1,min(float(payload.get('risk_pct') or 1),10.0))
        except Exception: risk_pct=1.0
        try: slippage_pct=max(0,min(float(payload.get('slippage_pct') or 0.05),2.0))
        except Exception: slippage_pct=0.05
        feed=str(payload.get('feed') or 'iex').strip().lower()
        if feed not in ('iex','sip'): feed='iex'

        from datetime import timedelta
        end=datetime.now(timezone.utc)
        fetch_days=max(max(periods)+180,900)
        fetch_start=end-timedelta(days=fetch_days)
        rows=[]; walk_rows=[]; errors=[]
        for symbol in symbols:
            try:
                params={'timeframe':'1Day','start':fetch_start.strftime('%Y-%m-%dT%H:%M:%SZ'),'end':end.strftime('%Y-%m-%dT%H:%M:%SZ'),'limit':10000,'feed':feed,'sort':'asc'}
                data=_alpaca_market_request('/v2/stocks/'+symbol+'/bars',params=params)
                all_bars=data.get('bars') if isinstance(data,dict) else []
                all_bars=[b for b in (all_bars or []) if all(k in b for k in ('o','h','l','c'))]
                if len(all_bars)<100:
                    errors.append({'symbol':symbol,'error':f'Histórico insuficiente ({len(all_bars)} barras).'})
                    continue
                for days in periods:
                    cutoff=end-timedelta(days=days)
                    bars=[]
                    for b in all_bars:
                        try: dt=datetime.fromisoformat(str(b.get('t') or '').replace('Z','+00:00'))
                        except Exception: dt=None
                        if dt is None or dt>=cutoff: bars.append(b)
                    if len(bars)<60:
                        rows.append({'symbol':symbol,'days':days,'ok':False,'error':f'Solo {len(bars)} barras.'})
                        continue
                    result=stonks_backtest.run_backtest(bars,strategy,capital,risk_pct,slippage_pct)
                    m=result['metrics']
                    rows.append({'symbol':symbol,'days':days,'ok':True,'bars':len(bars),
                        'return_pct':m['return_pct'],'cagr_pct':m['cagr_pct'],'max_drawdown_pct':m['max_drawdown_pct'],
                        'sharpe':m['sharpe'],'profit_factor':m['profit_factor'],'trades':m['trades'],
                        'win_rate_pct':m['win_rate_pct'],'expectancy_usd':m['expectancy_usd'],
                        'benchmark_return_pct':m['benchmark_return_pct'],'vs_benchmark_pct':m['vs_benchmark_pct']})
                wf=stonks_backtest.walk_forward(all_bars,strategy,capital,risk_pct,slippage_pct,folds=4,train_bars=126,test_bars=63)
                walk_rows.append({'symbol':symbol,**wf})
            except Exception as exc:
                errors.append({'symbol':symbol,'error':str(exc)})

        qualification=stonks_validation.assess_suite(rows,walk_rows)
        return jsonify({'ok':True,'paper':True,'orders_created':False,'strategy':strategy,'feed':feed,
            'symbols':symbols,'periods':periods,'rows':rows,'walk_forward':walk_rows,'errors':errors,
            'qualification':qualification,
            'parameters':{'capital':capital,'risk_pct':risk_pct,'slippage_pct':slippage_pct},
            'model':{'deterministic':True,'llm_tokens':0,'codex_required':False,'live_orders':False,'ranking':False,'auto_enable_paper':False}})
    except Exception as exc:
        return jsonify({'ok':False,'error':str(exc)}),502

@app.get('/api/stonks/alpaca/portfolio')
def stonks_alpaca_portfolio_api():
    """Return the current Paper account, positions and trading clock."""
    try:
        account=_alpaca_paper_request('/v2/account')
        positions=_alpaca_paper_request('/v2/positions')
        clock=_alpaca_paper_request('/v2/clock')
        equity=float(account.get('equity') or 0)
        last_equity=float(account.get('last_equity') or 0)
        day_pl=equity-last_equity
        return jsonify({'ok':True,'paper':True,
            'account':{
                'status':account.get('status'),'currency':account.get('currency'),
                'cash':account.get('cash'),'equity':account.get('equity'),
                'buying_power':account.get('buying_power'),'portfolio_value':account.get('portfolio_value'),
                'last_equity':account.get('last_equity'),'long_market_value':account.get('long_market_value'),
                'short_market_value':account.get('short_market_value')
            },
            'day_pl':day_pl,
            'positions':positions if isinstance(positions,list) else [],
            'market':{'is_open':bool(clock.get('is_open')),'timestamp':clock.get('timestamp'),'next_open':clock.get('next_open'),'next_close':clock.get('next_close')}
        })
    except Exception as exc:
        return jsonify({'ok':False,'error':str(exc)}),502

@app.get('/api/stonks/alpaca/positions')
def stonks_alpaca_positions_api():
    try:
        data=_alpaca_paper_request('/v2/positions')
        return jsonify({'ok':True,'paper':True,'positions':data if isinstance(data,list) else []})
    except Exception as exc:
        return jsonify({'ok':False,'error':str(exc)}),502

@app.get('/api/stonks/alpaca/position/<symbol>')
def stonks_alpaca_position_get_api(symbol):
    symbol=str(symbol or '').strip().upper()
    if not symbol or len(symbol)>20 or not symbol.replace('.','').replace('-','').isalnum():
        return jsonify({'ok':False,'error':'Símbolo no válido.'}),400
    try:
        data=_alpaca_paper_request('/v2/positions/'+symbol)
        return jsonify({'ok':True,'paper':True,'position':data})
    except Exception as exc:
        return jsonify({'ok':False,'error':str(exc)}),502

@app.post('/api/stonks/alpaca/order')
@_stonks_serialized
def stonks_alpaca_order_api():
    """Create a strictly Paper Alpaca order after server-side safety checks."""
    try:
        d=_stonks_read()
        if d.get('revoked'):
            return jsonify({'ok':False,'error':'El control operativo está revocado. Reautoriza antes de operar.'}),409
        if d.get('paused'):
            return jsonify({'ok':False,'error':'El motor está pausado. Pulsa Reanudar para habilitar órdenes Paper.'}),409
        if d.get('mode') != 'paper':
            return jsonify({'ok':False,'error':'ZAR Stonks solo permite órdenes Paper en esta versión.'}),409
        payload=request.get_json(silent=True) or {}
        symbol=(str(payload.get('symbol') or 'AAPL').strip().upper())
        side=str(payload.get('side') or 'buy').strip().lower()
        order_type=str(payload.get('type') or 'limit').strip().lower()
        tif=str(payload.get('time_in_force') or 'day').strip().lower()
        try: qty=float(payload.get('qty'))
        except Exception: qty=0
        try: limit_price=float(payload.get('limit_price')) if payload.get('limit_price') not in (None,'') else None
        except Exception: limit_price=None
        if not symbol or len(symbol)>20 or not symbol.replace('.','').replace('-','').isalnum():
            return jsonify({'ok':False,'error':'Símbolo no válido.'}),400
        if side not in ('buy','sell'):
            return jsonify({'ok':False,'error':'El lado debe ser buy o sell.'}),400
        if order_type not in ('market','limit'):
            return jsonify({'ok':False,'error':'Solo se permiten órdenes market o limit en este primer bloque.'}),400
        if tif not in ('day','gtc'):
            return jsonify({'ok':False,'error':'Time in force no válido. Usa day o gtc.'}),400
        if qty <= 0 or qty > 10000:
            return jsonify({'ok':False,'error':'Cantidad no válida.'}),400
        if order_type == 'limit' and (limit_price is None or limit_price <= 0):
            return jsonify({'ok':False,'error':'Una orden limit necesita un precio límite positivo.'}),400
        if order_type == 'market' and tif != 'day':
            return jsonify({'ok':False,'error':'Las órdenes market de este panel usan time in force day.'}),400

        # Conservative server-side cap. The existing control is denominated in EUR;
        # we use the same numeric ceiling in USD so we never exceed it because of FX assumptions.
        max_trade=float(d.get('max_trade_eur',25))
        estimated=qty*(limit_price or 0)
        # Alpaca Paper en este endpoint exige un valor mínimo de orden de 1 USD.
        # Validamos aquí para mostrar un error claro en ZAR y no enviar una petición que Alpaca rechazará.
        if order_type == 'limit' and estimated < 1.0:
            return jsonify({'ok':False,'error':f'Alpaca exige un valor mínimo de 1,00 USD por orden. El valor calculado es {estimated:.2f} USD. Aumenta la cantidad o el precio límite.'}),409
        if order_type == 'limit' and estimated > max_trade:
            return jsonify({'ok':False,'error':f'La orden supera el límite de seguridad configurado ({max_trade:.2f}).'}),409
        if order_type == 'market':
            try:
                t=_alpaca_market_request(f'/v2/stocks/{symbol}/trades/latest')
                last=(t.get('trades') or {}).get(symbol) or {}
                px=float(last.get('p') or 0)
                if not px:
                    return jsonify({'ok':False,'error':'No hay un último precio disponible para verificar el límite de seguridad. Usa una orden limit.'}),409
                market_estimated=qty*px
                if market_estimated < 1.0:
                    return jsonify({'ok':False,'error':f'Alpaca exige un valor mínimo de 1,00 USD por orden. El valor estimado es {market_estimated:.2f} USD. Aumenta la cantidad.'}),409
                if market_estimated > max_trade:
                    return jsonify({'ok':False,'error':f'La orden supera el límite de seguridad configurado ({max_trade:.2f}) según el último precio disponible.'}),409
            except Exception as exc:
                return jsonify({'ok':False,'error':'No se pudo verificar el precio antes de aplicar el límite de seguridad. Usa una orden limit.'}),409

        # Portfolio-level risk checks. These are Paper-only but deliberately enforced
        # server-side so the browser cannot bypass the configured limits.
        try:
            account=_alpaca_paper_request('/v2/account')
            equity=float(account.get('equity') or 0)
            last_equity=float(account.get('last_equity') or 0)
            daily_loss=max(0.0,last_equity-equity)
            max_daily=float(d.get('max_daily_loss_eur',10))
            if daily_loss >= max_daily:
                return jsonify({'ok':False,'error':f'El límite de pérdida diaria está alcanzado: {daily_loss:.2f} USD frente a un máximo configurado de {max_daily:.2f}.'}),409
            positions=_alpaca_paper_request('/v2/positions')
            if not isinstance(positions,list): positions=[]
            current=next((p for p in positions if str(p.get('symbol','')).upper()==symbol),None)
            if side=='sell':
                current_qty=float((current or {}).get('qty') or 0)
                if current_qty <= 0:
                    return jsonify({'ok':False,'error':'ZAR Stonks no permite vender una posición inexistente en este bloque Paper.'}),409
                if qty > current_qty + 1e-9:
                    return jsonify({'ok':False,'error':f'La cantidad a vender ({qty:g}) supera la posición Paper disponible ({current_qty:g}).'}),409
            elif order_type in ('limit','market'):
                current_value=abs(float((current or {}).get('market_value') or 0))
                order_value=estimated if order_type=='limit' else market_estimated
                max_position=float(d.get('max_position_pct',20))
                if equity <= 0 or max_position <= 0 or (current_value + order_value) > equity*(max_position/100.0):
                    return jsonify({'ok':False,'error':f'La posición de {symbol} superaría el máximo configurado del {max_position:.0f}% de la cartera.'}),409
        except Exception as exc:
            return jsonify({'ok':False,'error':'No se pudieron verificar los límites de cartera antes de enviar la orden. '+str(exc)}),409

        body={'symbol':symbol,'qty':str(qty),'side':side,'type':order_type,'time_in_force':tif}
        if order_type == 'limit': body['limit_price']=str(limit_price)
        # Submit through the Paper trading endpoint using JSON; credentials stay server-side.
        # Re-use the same credentials and Paper base URL, without ever exposing them to the client.
        key, secret=_alpaca_paper_credentials()
        import requests as _requests
        rr=_requests.post('https://paper-api.alpaca.markets/v2/orders', headers={'APCA-API-KEY-ID':key,'APCA-API-SECRET-KEY':secret,'Accept':'application/json','Content-Type':'application/json'}, json=body, timeout=12)
        try: data=rr.json()
        except Exception: data={'raw':rr.text[:1000]}
        if not rr.ok:
            msg=data.get('message') if isinstance(data,dict) else None
            return jsonify({'ok':False,'error':f'Alpaca Paper {rr.status_code}: {msg or "orden rechazada"}'}),502
        return jsonify({'ok':True,'paper':True,'order':data})
    except Exception as exc:
        return jsonify({'ok':False,'error':str(exc)}),502

@app.get('/api/stonks/alpaca/orders')
def stonks_alpaca_orders_api():
    try:
        status=request.args.get('status','all')
        if status not in ('open','closed','all'): status='all'
        data=_alpaca_paper_request('/v2/orders', params={'status':status,'limit':100,'direction':'desc','nested':'true'})
        return jsonify({'ok':True,'paper':True,'orders':data if isinstance(data,list) else []})
    except Exception as exc:
        return jsonify({'ok':False,'error':str(exc)}),502

@app.get('/api/stonks/alpaca/order/<order_id>')
def stonks_alpaca_order_get_api(order_id):
    try:
        data=_alpaca_paper_request('/v2/orders/'+str(order_id))
        return jsonify({'ok':True,'paper':True,'order':data})
    except Exception as exc:
        return jsonify({'ok':False,'error':str(exc)}),502

@app.delete('/api/stonks/alpaca/order/<order_id>')
@_stonks_serialized
def stonks_alpaca_order_cancel_api(order_id):
    try:
        # Cancellation remains available even when the engine is paused/revoked: emergency control must work.
        data=_alpaca_paper_request('/v2/orders/'+str(order_id), method='DELETE')
        return jsonify({'ok':True,'paper':True,'cancelled':True,'response':data})
    except Exception as exc:
        return jsonify({'ok':False,'error':str(exc)}),502

@app.post('/api/stonks/pause')
@_stonks_serialized
def stonks_pause_api():
    d=_stonks_read(); d['paused']=True; _stonks_write(d); return jsonify({'ok':True,'paused':True})

@app.post('/api/stonks/resume')
@_stonks_serialized
def stonks_resume_api():
    d=_stonks_read()
    if d.get('revoked'):
        return jsonify({'ok':False,'error':'El control está revocado; requiere reautorización.'}), 409
    d['paused']=False
    d['mode']='paper'
    _stonks_write(d)
    return jsonify({'ok':True,'paused':False,'revoked':False,'mode':'paper'})

@app.post('/api/stonks/revoke')
@_stonks_serialized
def stonks_revoke_api():
    d=_stonks_read(); d['paused']=True; d['revoked']=True; d['mode']='paper'; d['autonomous_engine']=False; _stonks_write(d)
    # Retain owner for read-only reconciliation while disabled/revoked.
    return jsonify({'ok':True,'paused':True,'revoked':True,'autonomous_engine':False})

@app.post('/api/stonks/restore')
@_stonks_serialized
def stonks_restore_api():
    # Restore only removes the revocation lock; the motor remains paused until the user explicitly resumes it.
    d=_stonks_read(); d['revoked']=False; d['paused']=True; d['mode']='paper'; _stonks_write(d)
    _stonks_audit_append('RESTAURACIÓN', {'message':'Control operativo restaurado; el motor permanece pausado hasta Reanudar.'})
    return jsonify({'ok':True,'paused':True,'revoked':False,'mode':'paper'})

@app.post('/api/stonks/controls')
@_stonks_serialized
def stonks_controls_api():
    payload=request.get_json(silent=True) or {}; d=_stonks_read()
    for key, default in [('max_trade_eur',25),('max_daily_loss_eur',10),('max_position_pct',20)]:
        try: val=float(payload.get(key, d.get(key,default)))
        except Exception: val=default
        d[key]=max(0,val)
    mode=str(payload.get('execution_mode',d.get('execution_mode','decision'))).strip().lower()
    if mode not in ('decision','shadow','paper_auto'): mode='decision'
    if mode=='shadow':
        active_owned = stonks_lifecycle.active_records(d) or d.get('pending_entries') or any(r.get('status')!='CERRADA' for r in d.get('managed_positions',{}).values())
        if active_owned:
            return jsonify({'ok':False,'error':'No se puede pasar a Shadow mientras existan posiciones/intenciones ZAR pendientes. Resuelve primero la exposición Paper.'}),409
    d['execution_mode']=mode
    d['max_position_pct']=min(100,d['max_position_pct'])
    d['position_lifecycle_enabled']=bool(payload.get('position_lifecycle_enabled',d.get('position_lifecycle_enabled',False)))
    try: d['stop_loss_pct']=max(0.0,min(50.0,float(payload.get('stop_loss_pct',d.get('stop_loss_pct',1.0)))))
    except Exception: d['stop_loss_pct']=1.0
    try: d['take_profit_pct']=max(0.0,min(100.0,float(payload.get('take_profit_pct',d.get('take_profit_pct',2.0)))))
    except Exception: d['take_profit_pct']=2.0
    _stonks_write(d)
    _stonks_audit_append('RISK',{'max_trade_eur':d['max_trade_eur'],'max_daily_loss_eur':d['max_daily_loss_eur'],'max_position_pct':d['max_position_pct'],'execution_mode':mode,'position_lifecycle_enabled':d['position_lifecycle_enabled'],'stop_loss_pct':d['stop_loss_pct'],'take_profit_pct':d['take_profit_pct']})
    return jsonify({'ok':True, **d})

@app.post('/api/stonks/engine')
@_stonks_serialized
def stonks_engine_api():
    payload=request.get_json(silent=True) or {}
    d=_stonks_read()
    enabled=bool(payload.get('enabled'))
    if enabled:
        owner=_stonks_engine_owner_read()
        me=_user_scope_id()
        if owner and owner!=me:
            with app.test_request_context('/api/stonks/engine/owner-check'):
                session['zar_user_id']=owner
                previous=_stonks_read()
            if (previous.get('autonomous_engine') or stonks_lifecycle.active_records(previous)
                    or previous.get('pending_entries')
                    or any(r.get('status')!='CERRADA' for r in previous.get('managed_positions',{}).values())):
                return jsonify({'ok':False,'error':'Otro espacio conserva el motor o posiciones/intenciones pendientes. Debe desactivarlo y resolver su exposición antes de transferir el control.'}),409
        symbols=[]
        for raw in str(payload.get('symbols') or ','.join(d.get('engine_symbols') or ['AAPL'])).split(','):
            sym=raw.strip().upper()
            if sym and sym not in symbols: symbols.append(sym)
        if not symbols: symbols=['AAPL']
        if len(symbols)>8: return jsonify({'ok':False,'error':'Máximo 8 símbolos para el motor autónomo.'}),400
        for sym in symbols:
            if len(sym)>20 or not sym.replace('.','').replace('-','').isalnum():
                return jsonify({'ok':False,'error':f'Símbolo no válido: {sym}.'}),400
        strategy=str(payload.get('strategy') or d.get('engine_strategy') or 'trend').strip().lower()
        timeframe=str(payload.get('timeframe') or d.get('engine_timeframe') or '1Min').strip()
        if strategy not in ('trend','mean_reversion'): strategy='trend'
        if timeframe not in ('1Min','5Min','15Min'): timeframe='1Min'
        if d.get('revoked'):
            return jsonify({'ok':False,'error':'Primero restaura el control de ZAR Stonks; después podrás activar el motor autónomo.'}),409
        if d.get('mode')!='paper':
            return jsonify({'ok':False,'error':'El motor autónomo solo funciona en modo Paper.'}),409
        requested_mode=str(payload.get('execution_mode') or d.get('execution_mode') or 'decision').strip().lower()
        if requested_mode not in ('shadow','paper_auto'):
            requested_mode='shadow'
        if requested_mode=='shadow' and (stonks_lifecycle.active_records(d) or d.get('pending_entries')):
            return jsonify({'ok':False,'error':'Shadow requiere no tener posiciones/intenciones ZAR activas.'}),409
        d['execution_mode']=requested_mode
        d['autonomous_engine']=True
        d['engine_symbols']=symbols
        d['engine_strategy']=strategy
        d['engine_timeframe']=timeframe
        d['engine_last_action']='Motor autónomo Paper activado; pendiente del siguiente ciclo.'
        _stonks_write(d); _stonks_engine_owner_write(me)
        _stonks_audit_append('MOTOR AUTÓNOMO',{'decision':'ACTIVADO','execution_mode':d.get('execution_mode'),'symbols':symbols,'strategy':strategy,'timeframe':timeframe,'paused':bool(d.get('paused'))})
        return jsonify({'ok':True,**d,'engine_owner':me})
    d['autonomous_engine']=False
    d['engine_last_action']='Motor autónomo Paper desactivado por el usuario.'
    _stonks_write(d)
    # Retain owner for read-only reconciliation while disabled/revoked.
    _stonks_audit_append('MOTOR AUTÓNOMO',{'decision':'DESACTIVADO'})
    return jsonify({'ok':True,**d,'engine_owner':_stonks_engine_owner_read()})

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
            "has_api_key": bool(cfg["api"]["api_key"]),
            "has_openai_key": bool((cfg.get("openai") or {}).get("api_key")),
            "openai_models": {k:v for k,v in (cfg.get("openai") or {}).items() if k.endswith("_model")},
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
    def workspace_probe(kind, version, mime, getter):
        from googleapiclient.discovery import build
        d=build('drive','v3',credentials=creds,cache_discovery=False)
        files=d.files().list(q=f"mimeType='{mime}' and trashed=false",pageSize=1,fields='files(id)').execute().get('files',[])
        if not files:
            return
        getter(build(kind, version, credentials=creds, cache_discovery=False), files[0]['id'])
    def docs(): workspace_probe('docs','v1','application/vnd.google-apps.document',lambda svc,fid: svc.documents().get(documentId=fid).execute())
    def sheets(): workspace_probe('sheets','v4','application/vnd.google-apps.spreadsheet',lambda svc,fid: svc.spreadsheets().get(spreadsheetId=fid,fields='spreadsheetId').execute())
    def slides(): workspace_probe('slides','v1','application/vnd.google-apps.presentation',lambda svc,fid: svc.presentations().get(presentationId=fid).execute())
    def forms(): workspace_probe('forms','v1','application/vnd.google-apps.form',lambda svc,fid: svc.forms().get(formId=fid).execute())

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
    elif bs.get("status") == "done_with_warnings": backup_state = "done_with_warnings"
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
        "version": "30.2.6",
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
            "progress": bs.get("progress", 0),
            "message": bs.get("message"),
            "current_service": bs.get("current_service"),
            "completed_services": bs.get("completed_services", 0),
            "total_services": bs.get("total_services", 0),
            "options": bs.get("options") or bstats.get("backup_options"),
            "service_states": bs.get("service_states") or {},
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
        payload = request.get_json(silent=True) or {}
        options = normalize_backup_options(payload.get("options"))
        return jsonify({"ok": True, **start_google_backup("manual", options=options)})
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

@app.get("/api/gmail/recent")
def api_gmail_recent():
    try:
        if not connected():
            return jsonify({"ok": False, "error": "Google/Gmail no está conectado."}), 401
        from .gmail import recent_messages
        limit=max(1,min(int(request.args.get("limit",10)),25))
        return jsonify({"ok": True, "messages": recent_messages("in:inbox", limit)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

@app.get("/api/gmail/message/<message_id>")
def api_gmail_message(message_id):
    try:
        if not connected():
            return jsonify({"ok": False, "error": "Google/Gmail no está conectado."}), 401
        from .gmail import get_message
        return jsonify({"ok": True, "message": get_message(message_id)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

@app.get("/api/ai/router")
def ai_router_status():
    try:
        from .smart_router import catalog as smart_catalog
    except ImportError:
        from smart_router import catalog as smart_catalog
    return jsonify({"ok": True, **smart_catalog(load())})

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
    if data.get("provider") in ("auto","api","local","openrouter"):
        cfg["provider"] = data["provider"]
    if isinstance(data.get("api"), dict):
        cfg["api"].update({k:v for k,v in data["api"].items() if k in ("base_url","api_key","model")})
    if isinstance(data.get("local"), dict):
        cfg["local"].update({k:v for k,v in data["local"].items() if k in ("base_url","model")})
    if isinstance(data.get("openai"), dict):
        cfg.setdefault("openai", {}).update({k:v for k,v in data["openai"].items() if k in ("base_url","api_key","economy_model","strong_model","max_model")})
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

    # Aprender de un documento recién adjuntado: usa la última referencia de archivo
    # guardada en el contexto de usuario y conserva el análisis en aprendizaje persistente.
    if re.search(r"\b(aprende|estudia|aprende de|analiza y aprende|memoriza)\b.*\b(documento|archivo|factura|nómina|nomina|pdf|imagen)\b", msg, re.I):
        try:
            last = get_context().get("last_uploaded_file") or {}
            file_id = last.get("id") if isinstance(last, dict) else None
            if file_id:
                learned = learn_from_file(file_id)
                analysis = learned.get("analysis") or {}
                reply = ("🧠 He aprendido de «%s».\n\nTipo: %s\nResumen: %s\n"
                         "He guardado su estructura y los datos detectados en tu espacio persistente de ZAR. "
                         "Puedes pedirme que busque, explique o compare cualquier dato del documento."
                         % (last.get("name","documento"), analysis.get("document_type","documento"), analysis.get("summary") or analysis.get("description") or "sin resumen"))
            else:
                reply="No tengo un documento recién adjuntado en el contexto. Sube el archivo y dime «aprende de este documento»."
            _remember_turn("user",msg); _remember_turn("assistant",reply)
            return reply
        except Exception as exc:
            reply=f"No he podido aprender del documento: {exc}"
            _remember_turn("user",msg); _remember_turn("assistant",reply)
            return reply

    # ZAR Learning: una petición explícita de "aprender/estudiar/dominar" crea
    # un proceso persistente de investigación y convierte el resultado en una habilidad.
    learning_match = re.match(r"^\s*(?:zar[,:]?\s*)?(?:quiero que aprendas|quiero que aprenda|quiero enseñarte|quiero enseñarte a|aprende|aprende a|estudia|domina|fórmate en|formate en|aprende todo lo necesario sobre|quiero que estudies|quiero que domines)\s+(.+)$", msg, re.I)
    if learning_match:
        try:
            topic = learning_match.group(1).strip().rstrip(".")
            # Mantener la petición original como objetivo; el proceso se ejecuta en segundo plano.
            job = start_learning(topic, msg, [])
            reply = (f"🧠 He iniciado el aprendizaje de «{topic}».\n\n"
                     "Voy a investigar fuentes públicas, organizar un currículo, comprobar conocimientos y guardar "
                     "el conocimiento y una habilidad reutilizable. El proceso continúa en segundo plano. "
                     "Puedes abrir 🧩 Habilidades para ver la fase, consultas, fuentes, tiempo transcurrido y estimación restante.")
            _remember_turn("user", msg); _remember_turn("assistant", reply)
            return reply
        except Exception as exc:
            reply=f"No he podido iniciar el aprendizaje: {exc}"
            _remember_turn("user",msg); _remember_turn("assistant",reply)
            return reply

    # ZAR Skills: una invocación explícita de una habilidad guardada tiene
    # prioridad sobre el enrutador general. La habilidad se ejecuta con el
    # mismo motor y herramientas que una petición normal, pero sus pasos quedan
    # fijados por el usuario y almacenados en el volumen persistente.
    skill = match_skill(msg)
    if skill:
        try:
            from .agent import api_agent, local_agent
            cfg = load()
            provider = cfg.get("provider")
            if provider == "api":
                runner = lambda prompt: api_agent(prompt, cfg)
            elif provider == "openrouter":
                runner = lambda prompt: api_agent(prompt, {**cfg, "provider": "openrouter"})
            elif provider == "local":
                runner = lambda prompt: local_agent(prompt, cfg)
            else:
                raise RuntimeError("Motor de IA no válido.")
            skill_result, used_skill = execute_skill(skill.get("id"), msg, runner)
            reply = skill_result
            if isinstance(reply, str) and reply.startswith("HE_EMAIL::"):
                data = json.loads(reply.split("::", 1)[1])
                _set_pending(_pending_email_from(data))
                set_focus("email_draft", data.get("subject") or "borrador actual")
                reply = _email_card(data, question=True)
            elif isinstance(reply, str) and reply.startswith("WORKSPACE_ACTION::"):
                data = json.loads(reply.split("::", 1)[1])
                pending = {"service": data.get("service", "Google Workspace"), "action": data.get("action", "realizar una acción"), "args": data.get("args") or {}}
                set_pending_workspace(pending)
                set_task_state("google workspace", (pending.get("service") or "workspace").lower(), "", pending.get("action", ""), "high", "awaiting_confirmation", f"Preparado para {pending.get('action','acción')} en {pending.get('service','Google Workspace')}")
                reply = f"⚠️ La habilidad «{used_skill.get('name')}» ha preparado la acción: {pending.get('action','acción')} en {pending.get('service','Google Workspace')}.\n\n¿Confirmas? Responde «sí» o «cancelar»."
            elif isinstance(reply, str) and reply.startswith("CONTACT_ACTION::"):
                data = json.loads(reply.split("::", 1)[1])
                pending = {"action": data.get("action"), "args": data.get("args") or {}}
                from .context import set_pending_contact
                set_pending_contact(pending)
                set_task_state("google contacts", "contact", "", pending.get("action", ""), "high", "awaiting_confirmation", f"Preparado para {pending.get('action','acción')}")
                reply = f"⚠️ La habilidad «{used_skill.get('name')}» ha preparado una acción de Google Contacts.\n\n¿Confirmas? Responde «sí» o «cancelar»."
            _remember_turn("user", msg)
            _remember_turn("assistant", reply)
            return reply
        except Exception as exc:
            reply = f"No he podido ejecutar la habilidad «{skill.get('name','')}»: {exc}"
            _remember_turn("user", msg)
            _remember_turn("assistant", reply)
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
                reply = _email_message_card(msg_data, summary=summary.strip(), draft=draft, title="Correo de Gmail · análisis y respuesta")
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
                reply = _email_message_card(msg_data, title="Correo de Gmail · lectura")
        except Exception as exc:
            reply = f"No he podido abrir el último correo: {exc}"

    elif isinstance(reply,str) and reply.startswith("DIRECT_GMAIL_SUMMARIZE::"):
        if LAST_EMAIL:
            try:
                reply = _email_summary_card(LAST_EMAIL, summarize_email(LAST_EMAIL))
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

@app.post("/api/video/projects/<pid>/media/<int:index>/split")
def video_project_media_split(pid,index):
    data=request.get_json(silent=True) or {}
    try:
        project=split_media(pid,index,data.get("at"))
        return jsonify({"ok":True,"project":project})
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
    try:
        skills_count = len(list_skills())
    except Exception:
        skills_count = 0
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
        "skills": skills_count,
        "research_reports": len(reports),
        "knowledge_sources": int(kstats.get("sources", 0) or 0),
        "knowledge_chunks": int(kstats.get("chunks", 0) or 0),
        "learning_topics": len(list_learning()),
        "learning_jobs": len(list_jobs()),
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
    saved, duplicates, errors = [], [], []
    for fs in files:
        try:
            item = save_upload(fs, note=note)
            path = files_dir() / item.get("category", "sin_clasificar") / item.get("stored_name", "")
            # Index immediately when possible. The status is persisted so the UI
            # can distinguish a saved file from a searchable/indexed file.
            try:
                raw = list_files()
                for x in raw:
                    if x.get("id") == item.get("id"):
                        x["indexing_status"] = "indexing"
                from .file_store import _save as _file_save
                _file_save(raw)
                index_file_from_disk(item, path)
                now = datetime.now(timezone.utc).isoformat()
                raw = list_files()
                for x in raw:
                    if x.get("id") == item.get("id"):
                        x.update({"indexing_status":"indexed","indexing_error":"","indexed_at":now})
                _file_save(raw)
            except Exception as exc:
                raw = list_files()
                for x in raw:
                    if x.get("id") == item.get("id"):
                        x.update({"indexing_status":"error","indexing_error":str(exc)})
                try:
                    from .file_store import _save as _file_save
                    _file_save(raw)
                except Exception:
                    pass
            item = get_file(item.get("id")) or item
            saved.append(public_item(item))
            set_last_uploaded_file(item)
            set_focus("file", item.get("name", "archivo"))
            set_task_state("guardar archivo", "file", item.get("id", ""), "guardar", "low", "file_saved", f"Archivo guardado: {item.get('name')}")
        except DuplicateFileError as exc:
            duplicates.append(public_item(exc.item))
        except Exception as exc:
            errors.append(str(exc))
    if not saved and not duplicates:
        return jsonify({"ok": False, "error": errors[0] if errors else "No se pudo guardar el archivo."}), 400
    return jsonify({"ok": True, "files": saved, "duplicates": duplicates, "errors": errors})

@app.get("/api/files")
def files_api():
    category = (request.args.get("category") or "").strip()
    query = (request.args.get("q") or "").strip()
    items = search_files(query, category, 500) if query else list_files(category)[:500]
    # v30.3: searching the Files panel also searches indexed document content,
    # not only filenames/notes. Metadata matches remain included.
    if query:
        try:
            from .knowledge import search_hybrid
            hits = [r for r in search_hybrid(query, limit=80) if r.get("source_type") == "file"]
            by_id = {x.get("id"): x for x in items}
            for hit in hits:
                fid = str(hit.get("source_id") or "")
                if not fid:
                    continue
                if fid not in by_id:
                    f = get_file(fid)
                    if f and (not category or f.get("category") == category):
                        by_id[fid] = f
            items = list(by_id.values())
            # Put stronger content/metadata matches first without changing stored data.
            rank = {str(h.get("source_id")): float(h.get("relevance") or 0) for h in hits}
            items.sort(key=lambda x: (rank.get(str(x.get("id")), 0), x.get("created_at", "")), reverse=True)
        except Exception:
            pass
    return jsonify({"ok": True, "query": query, "files": [public_item(x) for x in items]})

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
    ok = delete_file(file_id)
    if ok:
        try:
            from .knowledge import delete_source
            delete_source("file", file_id)
        except Exception:
            pass
    return jsonify({"ok": ok, "deleted": file_id if ok else None})

@app.post("/api/files/<file_id>/reindex")
def reindex_file_api(file_id):
    item = get_file(file_id)
    if not item:
        return jsonify({"ok": False, "error": "Archivo no encontrado."}), 404
    path = files_dir() / item.get("category", "sin_clasificar") / item.get("stored_name", "")
    if not path.exists():
        return jsonify({"ok": False, "error": "El archivo no está disponible en el almacenamiento."}), 404
    try:
        from .knowledge import index_file_from_disk
        result = index_file_from_disk(item, path)
        now = datetime.now(timezone.utc).isoformat()
        raw = list_files()
        for x in raw:
            if x.get("id") == file_id:
                x.update({"indexing_status":"indexed","indexing_error":"","indexed_at":now})
        from .file_store import _save as _file_save
        _file_save(raw)
        return jsonify({"ok": True, "file": public_item(get_file(file_id)), "index": result})
    except Exception as exc:
        raw = list_files()
        for x in raw:
            if x.get("id") == file_id:
                x.update({"indexing_status":"error","indexing_error":str(exc)})
        try:
            from .file_store import _save as _file_save
            _file_save(raw)
        except Exception:
            pass
        return jsonify({"ok": False, "error": str(exc), "file": public_item(get_file(file_id))}), 200

@app.post("/api/context/reset")
def reset_chat_context():
    clear_conversation(archive=True)
    reset_context(clear_email=True)
    return jsonify({"ok": True})

@app.get("/api/conversations")
def conversations_api():
    return jsonify({"ok": True, "conversations": list_conversations(80)})

@app.get("/api/conversations/search")
def conversations_search_api():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"ok": False, "error": "Falta la búsqueda."}), 400
    try:
        from .knowledge import search_hybrid
        allowed = {"chat", "memory", "file", "google_gmail", "google_drive_content", "google_calendar", "google_contact", "google_task"}
        rows = [r for r in search_hybrid(q, limit=40) if r.get("source_type") in allowed]
        return jsonify({"ok": True, "query": q, "results": rows[:30]})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

@app.get("/api/conversations/<thread_id>")
def conversation_archive_api(thread_id):
    item = get_conversation_archive(thread_id)
    if not item:
        return jsonify({"ok": False, "error": "Conversación no encontrada."}), 404
    return jsonify({"ok": True, "conversation": item})

@app.patch("/api/conversations/<thread_id>")
def conversation_archive_update_api(thread_id):
    data = request.get_json(silent=True) or {}
    title = data.get("title") if "title" in data else None
    starred = data.get("starred") if "starred" in data else None
    if title is not None and not str(title).strip():
        return jsonify({"ok": False, "error": "El nombre no puede estar vacío."}), 400
    item = update_conversation_archive(thread_id, title=title, starred=starred)
    if not item:
        return jsonify({"ok": False, "error": "Conversación no encontrada."}), 404
    return jsonify({"ok": True, "conversation": item})

@app.post("/api/conversations/<thread_id>/restore")
def conversation_archive_restore_api(thread_id):
    item = get_conversation_archive(thread_id)
    if not item:
        return jsonify({"ok": False, "error": "Conversación no encontrada."}), 404
    messages = item.get("messages") or []
    try:
        from .memory import _user_file, save
        save(_user_file("conversation.json"), messages[-40:])
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "conversation": item, "messages": messages})

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


@app.get("/api/learning")
def api_learning():
    # v30.10.11: the API never waits for network research. It only wakes the
    # durable worker; the worker persists progress after every bounded batch.
    # This makes progress visible immediately and prevents a slow search from
    # blocking the browser request.
    jobs = list_jobs()
    for job in jobs:
        if job.get("status") in ("queued", "researching", "synthesizing"):
            try:
                _ensure_learning_worker(job.get("id"))
            except Exception as exc:
                from .learning import _set_job
                _set_job(job.get("id"), status="error", phase="Detenido", message=f"No se pudo reactivar el aprendizaje: {exc}", heartbeat_at=time.time())
    return jsonify({"ok": True, "topics": list_learning(), "jobs": list_jobs()})

@app.get("/api/learning/<job_id>")
def api_learning_job(job_id):
    job = get_job(job_id)
    if not job:
        return jsonify({"ok": False, "error": "Aprendizaje no encontrado."}), 404
    if job.get("status") in ("queued", "researching", "synthesizing"):
        try:
            _ensure_learning_worker(job_id)
            job = get_job(job_id) or job
        except Exception as exc:
            from .learning import _set_job
            _set_job(job_id, status="error", phase="Detenido", message=f"No se pudo reactivar el aprendizaje: {exc}", heartbeat_at=time.time())
            job = get_job(job_id) or job
    return jsonify({"ok": True, "job": job})

@app.post("/api/learning/<job_id>/resume")
def api_learning_resume(job_id):
    try:
        return jsonify({"ok": True, "job": resume_learning(job_id)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

@app.delete("/api/learning/<job_id>")
def api_learning_delete(job_id):
    try:
        if not delete_learning(job_id):
            return jsonify({"ok": False, "error": "Aprendizaje no encontrado."}), 404
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

@app.post("/api/learning/start")
def api_learning_start():
    try:
        data=request.get_json(silent=True) or {}
        topic=str(data.get("topic") or "").strip()
        goal=str(data.get("goal") or "").strip()
        refs=data.get("references") or []
        if isinstance(refs,str):
            refs=[x.strip() for x in refs.splitlines() if x.strip()]
        return jsonify({"ok":True,"job":start_learning(topic,goal,refs)})
    except Exception as exc:
        return jsonify({"ok":False,"error":str(exc)}),400

@app.post("/api/learning/file/<file_id>")
def api_learning_file(file_id):
    try:
        return jsonify(learn_from_file(file_id))
    except Exception as exc:
        return jsonify({"ok":False,"error":str(exc)}),400

@app.get("/api/skills")
def api_skills():
    return jsonify({"ok": True, "skills": list_skills()})


@app.post("/api/skills")
def api_skill_create():
    try:
        data = request.get_json(silent=True) or {}
        return jsonify({"ok": True, "skill": create_skill(data)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.patch("/api/skills/<skill_id>")
def api_skill_update(skill_id):
    try:
        item = update_skill(skill_id, request.get_json(silent=True) or {})
        if not item:
            return jsonify({"ok": False, "error": "Habilidad no encontrada."}), 404
        return jsonify({"ok": True, "skill": item})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.delete("/api/skills/<skill_id>")
def api_skill_delete(skill_id):
    if not delete_skill(skill_id):
        return jsonify({"ok": False, "error": "Habilidad no encontrada."}), 404
    return jsonify({"ok": True})


@app.post("/api/skills/<skill_id>/execute")
def api_skill_execute(skill_id):
    try:
        data = request.get_json(silent=True) or {}
        message = str(data.get("message") or "").strip()
        if not message:
            return jsonify({"ok": False, "error": "Indica qué quieres hacer con esta habilidad."}), 400
        from .agent import api_agent, local_agent
        cfg = load()
        provider = cfg.get("provider")
        if provider == "api":
            runner = lambda prompt: api_agent(prompt, cfg)
        elif provider == "openrouter":
            runner = lambda prompt: api_agent(prompt, {**cfg, "provider": "openrouter"})
        elif provider == "local":
            runner = lambda prompt: local_agent(prompt, cfg)
        else:
            raise RuntimeError("Motor de IA no válido.")
        result, skill = execute_skill(skill_id, message, runner)
        if isinstance(result, str) and result.startswith("HE_EMAIL::"):
            draft = json.loads(result.split("::", 1)[1])
            _set_pending(_pending_email_from(draft))
            set_focus("email_draft", draft.get("subject") or "borrador actual")
            result = "He preparado un borrador de correo y lo he dejado pendiente de confirmación en ZAR. Revisa el chat para continuar."
        elif isinstance(result, str) and result.startswith("WORKSPACE_ACTION::"):
            action = json.loads(result.split("::", 1)[1])
            pending = {"service": action.get("service", "Google Workspace"), "action": action.get("action", "acción"), "args": action.get("args") or {}}
            set_pending_workspace(pending)
            set_task_state("google workspace", (pending.get("service") or "workspace").lower(), "", pending.get("action", ""), "high", "awaiting_confirmation", f"Preparado para {pending.get('action','acción')}")
            result = f"He preparado {pending.get('action','acción')} en {pending.get('service','Google Workspace')}. Confírmalo desde el chat."
        _remember_turn("user", message)
        _remember_turn("assistant", str(result))
        active_skills = [{"id": s.get("id"), "name": s.get("name"), "enabled": True} for s in list_skills() if s.get("enabled", True)]
        return jsonify({"ok": True, "result": str(result), "skill": skill, "active_skills": active_skills})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.get("/api/models")
def api_models():
    """Expose the active ZAR multi-model map without exposing API keys."""
    try:
        from .model_router import catalog
    except ImportError:
        from model_router import catalog
    return jsonify({"ok": True, "models": catalog()})

_stonks_engine_thread=threading.Thread(target=_stonks_engine_loop, name='zar-stonks-paper-engine', daemon=True)
_stonks_engine_thread.start()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT','8765')), debug=False)
