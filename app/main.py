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
import base64
from functools import wraps
from contextlib import contextmanager
from . import stonks_lifecycle, stonks_preflight, stonks_agents, stonks_news, stonks_dataplane, stonks_selftest, stonks_stream, subagent_orchestrator, stonks_backtest, stonks_validation, stonks_shadow, stonks_learning, stonks_automaton, stonks_execution, stonks_readiness, stonks_profitability
from . import holdings, company_runtime, commerce_company, media_company, web_agency, sites_company, jev_decision, social_publish, voice_pro
from datetime import datetime, timezone
from urllib.parse import quote as urlquote
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

def _write_job(job_id, status, reply=None, error=None, action=None, user_id=None, skills=None, confirmation=None):
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
    if confirmation is not None:
        payload["confirmation"] = confirmation
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

def _run_chat_job(job_id, msg, user_id, session_snapshot=None):
    """Run chat work in a background thread with an isolated Flask request context.

    Several mature ZAR paths (pending confirmations, Google Workspace/OAuth helpers,
    browser identity) legitimately read Flask ``session``. Background threads do
    not inherit the originating request context, so reconstruct the minimum context
    explicitly instead of letting those helpers touch Flask proxies out of context.
    """
    set_current_user(user_id)
    try:
        with app.test_request_context('/api/chat', method='POST', json={'message': msg}):
            for key, value in dict(session_snapshot or {}).items():
                try:
                    session[key] = value
                except Exception:
                    pass
            session['zar_user_id'] = user_id
            session.modified = True
            reply = _clean_model_ui_markup(_process_chat_message(msg))
            # Final confirmation bridge: an analyze-first Workspace turn may end with
            # a perfectly valid confirmation question after the structured file analysis,
            # but without a pending payload visible to the job yet. Prepare the business
            # sync here, before serialising the job result, so Confirmar/Cancelar appear
            # in this very first response instead of requiring a second chat turn.
            ctx_after = _ctx()
            if not ctx_after.get("pending_workspace") and _looks_like_confirmation_plan(reply):
                try:
                    _prepare_business_sync_pending(msg, reply)
                except Exception:
                    pass
                ctx_after = _ctx()
            action = (ctx_after.get("last_media") or None)
            confirmation = None
            if ctx_after.get("pending_workspace"):
                pw = ctx_after.get("pending_workspace") or {}
                confirmation = {"required": True, "kind": "workspace", "title": pw.get("service") or "Google Workspace", "action": pw.get("action") or "acción pendiente"}
            elif ctx_after.get("pending_contact"):
                confirmation = {"required": True, "kind": "contact", "title": "Google Contacts", "action": (ctx_after.get("pending_contact") or {}).get("action") or "modificar contacto"}
            elif ctx_after.get("pending_email"):
                confirmation = {"required": True, "kind": "email", "title": "Gmail", "action": "enviar correo"}
            elif (ctx_after.get("pending_calendar") or {}).get("event"):
                confirmation = {"required": True, "kind": "calendar", "title": "Google Calendar", "action": "crear evento"}
        _write_job(job_id, "done", reply=reply, confirmation=confirmation, action=( {"type":"open_url","url":action.get("url"),"platform":action.get("platform"),"query":action.get("query")} if action and action.get("url") else None ))
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
    allowed = {"login","health","oauth2callback","connect_google","connect_gmail","holdings_media_public_video_api","distributed_nodes.poll","distributed_nodes.claim","distributed_nodes.health","distributed_nodes.inference","agency_stripe_webhook"}
    if request.endpoint in allowed or request.path.startswith("/static/"):
        return None
    if _auth_enabled() and not _authorized():
        if request.path.startswith("/api/"):
            return jsonify({"error":"No autenticado"}), 401
        return redirect("/login")

from .node_coordinator import register as register_node_coordinator
register_node_coordinator(app)

@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "zar", "version": (Path(__file__).parent / "VERSION.txt").read_text().strip()})

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
    # Business/trading workspaces must remain usable without Google OAuth.
    # Gmail/Drive retain their existing connection and authorization gates.
    return render_template("index.html")


# --- ZAR Stonks control plane (broker-agnostic, paper-first) ---
_STONKS_DIR = Path(os.environ.get('ZAR_DATA_DIR', '/data')) / 'stonks'
_STONKS_DIR.mkdir(parents=True, exist_ok=True)
# Serialize worker and HTTP mutations across threads/processes on the persistent volume.
_STONKS_LOCK = threading.RLock()
_STONKS_LOCK_DEPTH = threading.local()
# Set only inside the Gunicorn process that owns engine.lock. Other web workers
# must never create duplicate market-stream sockets.
_STONKS_ENGINE_OWNER_PID = None

def _stonks_process_owns_engine():
    return _STONKS_ENGINE_OWNER_PID == os.getpid()

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
        from flask import has_request_context
        if has_request_context():
            payload = request.get_json(silent=True) or {}
            if (str(payload.get('mode', 'paper')).lower() != 'paper' or
                    payload.get('live_trading_enabled') or payload.get('execution_mode') == 'live'):
                return jsonify({'ok':False, 'error':'LIVE BLOQUEADO'}),409
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
        'engine_symbols': ['AAPL','MSFT','SPY','BTC/USD','ETH/USD','SOL/USD','DOGE/USD'],
        'engine_auto_universe': True,
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
        'shadow_last_signal_count': 0,
        'shadow_outcome_summary': {},
        'shadow_outcome_last_update': None,
        'data_plane_telemetry': {},
        'stream_watchlist_equities': ['AAPL','MSFT','SPY','QQQ'],
        'stream_watchlist_crypto': ['BTC/USD','ETH/USD','SOL/USD','DOGE/USD'],
        'crypto_universe_cache': {},
        'paper_scalp_mode': True,
        'paper_min_net_profit_usd': 0.10,
        'paper_cost_buffer_bps': 20.0,
        'stream_watchlist_options': [],
        'market_stream_snapshot': {},
        'paper_learning_journal_count': 0,
        'paper_learning': {},
        'paper_learning_last_update': None,
        'paper_learning_enabled': True,
        'paper_profitability_enabled': True,
        'paper_min_signal_quality': 55.0,
        'paper_symbol_cooldown_minutes': 15,
        'paper_max_entries_per_symbol_day': 4,
        'paper_crypto_cooldown_minutes': 3,
        'paper_crypto_max_entries_per_symbol_day': 16,
        'paper_last_entry_at': {},
        'paper_entry_counts': {},
        'paper_quality_seen': {},
        'paper_quality_stats': {},
        'automaton': stonks_automaton.default_state()
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

def _stonks_learning_file():
    return _STONKS_DIR / f"{_user_scope_id()}_paper_learning.json"

def _stonks_learning_read():
    p=_stonks_learning_file()
    if not p.exists():
        return {'journal':[]}
    # An unreadable existing journal is not an empty journal: never overwrite it.
    try:
        data=json.loads(p.read_text(encoding='utf-8'))
        rows=data.get('journal') if isinstance(data,dict) else None
        if not isinstance(rows,list) or any(not isinstance(row,dict) or not row.get('id') for row in rows):
            raise ValueError('Invalid journal')
        return {'journal':rows}
    except (OSError, ValueError) as exc:
        raise RuntimeError('Journal Paper no verificable; se conserva sin cambios') from exc


def _stonks_learning_write(rows):
    _stonks_atomic_json(_stonks_learning_file(), {
        'version':1, 'updated_at':datetime.now(timezone.utc).isoformat(),
        'paper_only':True, 'risk_authority':False, 'live_authority':False,
        'journal':list(rows or [])
    })

def _stonks_learning_update_state(d):
    store=_stonks_learning_read()
    d['paper_learning_journal']=list(store.get('journal') or [])
    update=stonks_learning.ingest(d)
    rows=d.pop('paper_learning_journal', [])
    d['paper_learning_journal_count']=len(rows)
    if update.get('added'):
        _stonks_learning_write(rows)
    return update

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
        if isinstance(page,list): page=[_stonks_normalize_broker_row(x) for x in page]
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
    if isinstance(positions,list): positions=[_stonks_normalize_broker_row(x) for x in positions]
    if isinstance(orders,list): orders=[_stonks_normalize_broker_row(x) for x in orders]
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
    row=_alpaca_paper_request('/v2/orders:by_client_order_id', params={'client_order_id':cid}, missing_ok=True)
    return _stonks_normalize_broker_row(row) if row else row


def _stonks_submit_paper_order(body):
    return stonks_execution.PaperExecutionAdapter(requests.post).submit(
        body, _stonks_read(), _alpaca_paper_credentials())


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
    if method.upper() not in ('GET', 'DELETE'):
        raise RuntimeError('Usar el adapter Paper para enviar ordenes')
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


def _stonks_market_clock_snapshot():
    """Return a fresh, validated Alpaca Paper market clock.

    UI/orchestration callers must not infer market state from a persisted agent
    trace.  The broker clock is authoritative; malformed/stale responses are
    reported as unavailable rather than silently rendered as "market closed".
    """
    clock = _alpaca_paper_request('/v2/clock')
    if not isinstance(clock, dict) or not isinstance(clock.get('is_open'), bool):
        raise RuntimeError('Reloj de mercado de Alpaca no válido')
    stamp = clock.get('timestamp')
    age_seconds = None
    if stamp:
        try:
            dt = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            age_seconds = max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds())
            # A broker clock should represent "now".  Do not turn a stale or
            # cached payload into a false CLOSED gate.
            if age_seconds > 120:
                raise RuntimeError(f'Reloj de mercado de Alpaca obsoleto ({age_seconds:.0f}s)')
        except RuntimeError:
            raise
        except Exception:
            raise RuntimeError('Timestamp del reloj de mercado de Alpaca no válido')
    return {
        'is_open': clock.get('is_open'),
        'timestamp': stamp,
        'next_open': clock.get('next_open'),
        'next_close': clock.get('next_close'),
        'age_seconds': round(age_seconds, 1) if age_seconds is not None else None,
        'received_at': datetime.now(timezone.utc).isoformat(),
        'source': 'alpaca_paper_clock',
    }

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


def _stonks_is_crypto(symbol):
    return '/' in str(symbol or '').replace('-', '/')


def _stonks_symbol_key(symbol):
    """Normalize user/engine crypto symbols to Alpaca pair form when possible."""
    s=str(symbol or '').strip().upper().replace('-', '/')
    if '/' in s:
        return s
    # Alpaca may expose compact crypto symbols in some account payloads.
    for quote in ('USDT','USDC','USD'):
        if s.endswith(quote) and len(s) > len(quote):
            return s[:-len(quote)] + '/' + quote
    return s


def _stonks_asset_path(symbol):
    return '/v2/assets/' + urlquote(_stonks_symbol_key(symbol), safe='')


def _stonks_normalize_broker_row(row):
    if not isinstance(row, dict):
        return row
    out=dict(row)
    if out.get('symbol'):
        out['symbol']=_stonks_symbol_key(out.get('symbol'))
    return out


def _stonks_crypto_clock():
    now=datetime.now(timezone.utc).isoformat()
    return {'is_open':True,'timestamp':now,'next_open':None,'next_close':None,
            'source':'alpaca_crypto_24_7','received_at':now}


def _stonks_discover_crypto_universe(d, limit=4, force=False):
    """Discover a small, liquid Paper crypto universe from Alpaca.

    Keeps BTC/ETH/SOL when tradable and reserves at least one slot for a
    meme-style asset when Alpaca exposes one with usable liquidity/spread.
    This selector has no order authority.
    """
    now=datetime.now(timezone.utc)
    cache=d.get('crypto_universe_cache') or {}
    try:
        stamp=datetime.fromisoformat(str(cache.get('updated_at') or '').replace('Z','+00:00'))
        if stamp.tzinfo is None: stamp=stamp.replace(tzinfo=timezone.utc)
        if not force and (now-stamp.astimezone(timezone.utc)).total_seconds() < 900 and cache.get('selected'):
            return list(cache.get('selected') or [])[:limit]
    except Exception:
        pass
    try:
        assets=_alpaca_paper_request('/v2/assets', params={'status':'active','asset_class':'crypto'})
        if not isinstance(assets,list):
            raise RuntimeError('Lista de activos crypto no válida')
        rows=[]
        for a in assets:
            raw=_stonks_symbol_key(a.get('symbol'))
            if not raw.endswith('/USD'):
                continue
            if a.get('status')!='active' or a.get('tradable') is not True:
                continue
            rows.append({'symbol':raw,'name':str(a.get('name') or ''),'asset':a})
        if not rows:
            raise RuntimeError('No hay pares crypto USD activos/tradables')
        meme_words=('DOGE','SHIB','PEPE','BONK','WIF','FLOKI','TRUMP','MEME','PENGU','MOG','BRETT','BABYDOGE')
        preferred=['BTC/USD','ETH/USD','SOL/USD']
        candidates=[r['symbol'] for r in rows]
        # Snapshots let the selector reject extremely illiquid/wide-spread pairs.
        snapshots={}
        try:
            payload=_alpaca_market_request('/v1beta3/crypto/us/snapshots', params={'symbols':','.join(candidates[:80])})
            snapshots=(payload.get('snapshots') or {}) if isinstance(payload,dict) else {}
        except Exception:
            snapshots={}
        scored=[]
        for row in rows:
            sym=row['symbol']; snap=snapshots.get(sym) or {}
            daily=snap.get('dailyBar') or {}; quote=snap.get('latestQuote') or {}
            try: price=float((snap.get('latestTrade') or {}).get('p') or daily.get('c') or 0)
            except Exception: price=0.0
            try: vol=float(daily.get('v') or 0)
            except Exception: vol=0.0
            try:
                bid=float(quote.get('bp') or 0); ask=float(quote.get('ap') or 0)
                mid=(bid+ask)/2 if bid>0 and ask>0 else price
                spread=((ask-bid)/mid*100) if mid and bid>0 and ask>=bid else None
            except Exception: spread=None
            liquidity=max(0.0, price*vol)
            meme=any(w in (sym+' '+row['name']).upper() for w in meme_words)
            # Keep unknown spread assets eligible, but heavily penalize very wide ones.
            spread_penalty=(spread or 0.25)*4.0
            score=(__import__('math').log10(liquidity+1.0) if liquidity>0 else 0.0)-spread_penalty+(0.35 if meme else 0.0)
            if spread is not None and spread > 1.25:
                score -= 5.0
            scored.append({'symbol':sym,'score':score,'meme':meme,'spread_pct':spread,'notional_volume':liquidity})
        selected=[]
        tradable={x['symbol'] for x in scored}
        for sym in preferred:
            if sym in tradable and sym not in selected:
                selected.append(sym)
        memes=sorted((x for x in scored if x['meme'] and x['symbol'] not in selected), key=lambda x:x['score'], reverse=True)
        if memes and len(selected)<limit:
            selected.append(memes[0]['symbol'])
        for x in sorted(scored,key=lambda x:x['score'],reverse=True):
            if len(selected)>=limit: break
            if x['symbol'] not in selected:
                selected.append(x['symbol'])
        d['crypto_universe_cache']={'updated_at':now.isoformat(),'selected':selected[:limit],
            'meme_candidates':[x['symbol'] for x in memes[:8]],
            'ranking':scored[:40]}
        _stonks_write(d)
        return selected[:limit]
    except Exception as exc:
        fallback=[x for x in (d.get('stream_watchlist_crypto') or ['BTC/USD','ETH/USD','SOL/USD','DOGE/USD']) if x]
        d['crypto_universe_cache']={'updated_at':now.isoformat(),'selected':fallback[:limit],'error':str(exc)[:240]}
        _stonks_write(d)
        return fallback[:limit]


def _stonks_engine_universe(d):
    if not bool(d.get('engine_auto_universe', True)):
        return list(d.get('engine_symbols') or ['AAPL'])[:8]
    equities=[]
    for raw in (d.get('stream_watchlist_equities') or ['AAPL','MSFT','SPY','QQQ']):
        s=_stonks_symbol_key(raw)
        if s and not _stonks_is_crypto(s) and s not in equities:
            equities.append(s)
        if len(equities)>=4: break
    crypto=_stonks_discover_crypto_universe(d, 4)
    universe=(equities+crypto)[:8]
    if universe != list(d.get('engine_symbols') or []):
        d['engine_symbols']=universe
        _stonks_write(d)
    return universe or ['AAPL']


def _stonks_latest_price(symbol):
    symbol=_stonks_symbol_key(symbol)
    if _stonks_is_crypto(symbol):
        payload=_alpaca_market_request('/v1beta3/crypto/us/latest/trades', params={'symbols':symbol})
        last=((payload.get('trades') or {}).get(symbol) or (payload.get('trades') or {}).get(symbol.replace('/','')) or {}) if isinstance(payload,dict) else {}
        return last, _stonks_crypto_clock()
    payload=_alpaca_market_request(f'/v2/stocks/{symbol}/trades/latest', params={'feed':'iex'})
    last=(payload.get('trade') or {}) if isinstance(payload,dict) else {}
    if not last and isinstance(payload,dict):
        last=(payload.get('trades') or {}).get(symbol) or {}
    return last, _stonks_market_clock_snapshot()


def _stonks_refresh_shadow_outcomes(d, force=False):
    """Refresh Shadow outcomes from completed 1-minute IEX bars.

    This is observational only. It never calls an order endpoint and is rate-limited
    to roughly once per minute even though the main engine runs every ~5 seconds.
    """
    rows=list(d.get('shadow_log') or [])
    if not rows:
        d['shadow_outcome_summary']=stonks_shadow.summarize([])
        return d, {'agent':'shadow_outcome','status':'idle','detail':'Sin señales Shadow que evaluar','data':{'signals':0,'orders_created':0},'timestamp':datetime.now(timezone.utc).isoformat()}
    now=datetime.now(timezone.utc)
    try:
        last=d.get('shadow_outcome_last_update')
        if last and not force:
            dt=datetime.fromisoformat(str(last).replace('Z','+00:00'))
            if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
            if (now-dt.astimezone(timezone.utc)).total_seconds() < 50:
                summary=stonks_shadow.summarize(rows)
                d['shadow_outcome_summary']=summary
                return d, {'agent':'shadow_outcome','status':'idle','detail':'Outcome cache vigente; sin llamadas extra','data':summary,'timestamp':now.isoformat()}
    except Exception:
        pass
    pending=[x for x in rows if x.get('outcome_status')!='complete' and x.get('timestamp') and x.get('symbol') and float(x.get('price') or 0)>0]
    if not pending:
        summary=stonks_shadow.summarize(rows)
        d['shadow_outcome_summary']=summary
        d['shadow_outcome_last_update']=now.isoformat()
        return d, {'agent':'shadow_outcome','status':'ok','detail':f"{summary.get('complete',0)} outcome(s) completos · 0 órdenes",'data':summary,'timestamp':now.isoformat()}
    symbols=[]
    for x in pending:
        s=str(x.get('symbol') or '').upper()
        if s and s not in symbols: symbols.append(s)
    starts=[]
    for x in pending:
        try: starts.append(datetime.fromisoformat(str(x['timestamp']).replace('Z','+00:00')).astimezone(timezone.utc))
        except Exception: pass
    if not starts:
        return d, {'agent':'shadow_outcome','status':'idle','detail':'Timestamps Shadow no válidos','data':{'orders_created':0},'timestamp':now.isoformat()}
    from datetime import timedelta
    start=min(starts)-timedelta(minutes=2)
    bars={}
    equity_symbols=[x for x in symbols if not _stonks_is_crypto(x)]
    crypto_symbols=[x for x in symbols if _stonks_is_crypto(x)]
    def _pages(path, group, extra=None):
        if not group: return
        params={
            'symbols':','.join(group),'timeframe':'1Min','start':start.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'end':now.strftime('%Y-%m-%dT%H:%M:%SZ'),'limit':10000,'sort':'asc'
        }
        if extra: params.update(extra)
        seen_tokens=set()
        for _ in range(8):
            payload=_alpaca_market_request(path,params=dict(params))
            for sym, page in (payload.get('bars') or {}).items():
                bars.setdefault(_stonks_symbol_key(sym),[]).extend(page or [])
            token=payload.get('next_page_token')
            if not token: return
            if token in seen_tokens:
                raise RuntimeError('Paginación Outcome repetida; snapshot incompleto')
            seen_tokens.add(token); params['page_token']=token
        raise RuntimeError('Histórico Outcome demasiado extenso; snapshot incompleto')
    _pages('/v2/stocks/bars', equity_symbols, {'feed':'iex'})
    _pages('/v1beta3/crypto/us/bars', crypto_symbols)
    rows=stonks_shadow.update_log(rows,bars,now=now)
    summary=stonks_shadow.summarize(rows)
    d['shadow_log']=rows[-stonks_shadow.MAX_EVENTS:]
    d['shadow_outcome_summary']=summary
    d['shadow_outcome_last_update']=now.isoformat()
    return d, {'agent':'shadow_outcome','status':'ok','detail':f"{summary.get('complete',0)} completos · {summary.get('pending',0)} pendientes · 0 órdenes",'data':summary,'timestamp':now.isoformat()}

def _stonks_stream_plan(d, activate=None):
    """Build the zero-token watch plan. Only the engine-lock owner opens sockets.

    Web workers return the last persisted snapshot so UI requests cannot create
    duplicate WebSocket connections in a multi-process Gunicorn deployment.
    """
    activate = activate is not False and _stonks_process_owns_engine()
    equities=[]
    exposure = (d.get('engine_last_positions') or []) + (d.get('engine_last_open_orders') or [])
    option_symbols = {r.get('symbol') for r in exposure if r.get('asset_class') == 'us_option'} | set(d.get('stream_watchlist_options') or [])
    priority = [r.get('symbol') for r in exposure]
    priority += [r.get('symbol') for r in [t.get('data') or {} for t in (d.get('agent_last_trace') or [])] if r.get('signal') in ('BUY', 'SELL')]
    for raw in priority + list(d.get('engine_symbols') or []) + list(d.get('stream_watchlist_equities') or []):
        s=str(raw or '').strip().upper()
        if s and '/' not in s and s not in option_symbols and s not in equities:
            equities.append(s)
    crypto=[]
    for raw in [s for s in priority if '/' in str(s)] + list(d.get('stream_watchlist_crypto') or []):
        s=str(raw or '').strip().upper().replace('-', '/')
        if s and s not in crypto:
            crypto.append(s)
    options=[]
    for raw in [s for s in priority if s in option_symbols] + list(d.get('stream_watchlist_options') or []):
        s=str(raw or '').strip().upper()
        if s and s not in options:
            options.append(s)
    if activate:
        stonks_stream.MANAGER.configure(equities=equities, crypto=crypto, options=options)
        status = stonks_stream.MANAGER.status(limit=30)
        status['process_owner'] = True
        status['owner_pid'] = os.getpid()
        return status
    snap = stonks_stream.refresh_snapshot(d.get('market_stream_snapshot') or {})
    if snap:
        snap['process_owner'] = False
        snap['served_from_persisted_snapshot'] = True
        return snap
    return {
        'architecture':'realtime_zero_token_stream', 'zero_tokens':True, 'order_authority':False,
        'watchlist':{'equities':equities,'crypto':crypto,'options':options},
        'feeds':{}, 'latest':[], 'process_owner':False, 'served_from_persisted_snapshot':True,
        'updated_at':datetime.now(timezone.utc).isoformat(),
    }

def _stonks_zero_token_health(d, scope_id):
    stonks_dataplane.PLANE.sync_state(d, scope_id)
    health=stonks_selftest.run(d, stonks_agents.describe(), d.get('data_plane_telemetry') or {})
    d['stonks_self_test']=health
    return health

@_stonks_serialized
def _stonks_engine_cycle(scope_id):
    """Run one autonomous Paper cycle for the single authorized Stonks owner.
    Reconciliation always runs; orders require explicit persisted authorization.
    """
    with app.test_request_context('/api/stonks/engine/cycle', method='POST'):
        session['zar_user_id']=scope_id
        d=_stonks_read()
        _automaton=stonks_automaton.ensure(d)
        if _automaton.get('state') in ('RUNNING','PAUSED'):
            stonks_automaton.heartbeat(d, 'THINK' if _automaton.get('state')=='RUNNING' else 'PAUSED', detail='Heartbeat del ciclo servidor')
            _stonks_write(d)
        stonks_dataplane.PLANE.hydrate(scope_id, d.get('data_plane_telemetry'))
        stonks_dataplane.PLANE.begin_cycle(scope_id)
        _stream_status=_stonks_stream_plan(d, activate=True)
        symbols=_stonks_engine_universe(d)
        strategy=d.get('engine_strategy') or 'trend'
        timeframe=d.get('engine_timeframe') or '1Min'
        try:
            agent_trace=[]
            recon, clock, market_trace = stonks_agents.SUPERVISOR.market.snapshot(
                scope_id, _stonks_reconcile_paper_state, lambda: _alpaca_paper_request('/v2/clock'))
            agent_trace.append(market_trace)
            # Zero-token Data Plane: news is refreshed on its own TTL, not every 5-second cycle.
            news_by_symbol = {}
            for _sym in symbols[:8]:
                try:
                    news_ctx, news_cache = stonks_dataplane.PLANE.news(
                        scope_id, _sym, lambda sym=_sym: stonks_news.get_context(sym), ttl=300.0)
                    news_by_symbol[_sym] = news_ctx
                    agent_trace.append({
                        'agent':'news_sentiment','status':'ok' if news_ctx.get('ok') else 'idle',
                        'detail':f"{_sym}: {news_ctx.get('sentiment','neutral')} · {'cache' if news_cache.get('cached') else 'actualizado'} · 0 tokens",
                        'data':{'symbol':_sym,'sentiment':news_ctx.get('sentiment'),'sentiment_score':news_ctx.get('sentiment_score'),
                                'source_count':len(news_ctx.get('items') or []),'cached':bool(news_cache.get('cached')),
                                'public_only':True,'order_authority':False},
                        'timestamp':datetime.now(timezone.utc).isoformat()})
                except Exception as _news_exc:
                    agent_trace.append({'agent':'news_sentiment','status':'idle','detail':f'{_sym}: noticias no disponibles', 'data':{'error':str(_news_exc)[:240]}, 'timestamp':datetime.now(timezone.utc).isoformat()})
            lifecycle, position_trace = stonks_agents.SUPERVISOR.positions.run(
                scope_id, recon, clock, _stonks_manage_positions)
            agent_trace.append(position_trace)
            d = _stonks_read()
            learning_update = _stonks_learning_update_state(d) if d.get('paper_learning_enabled', True) else {'added':[], 'summary':d.get('paper_learning') or {}}
            if learning_update.get('added'):
                _stonks_write(d)
                _stonks_audit_append('PAPER LEARNING', {
                    'new_trades':len(learning_update['added']),
                    'journal_count':int(d.get('paper_learning_journal_count') or 0),
                    'risk_authority':False, 'live_authority':False
                })
            agent_trace.append({
                'agent':'paper_learning','status':'ok',
                'detail':f"Learning Paper · {int(d.get('paper_learning_journal_count') or 0)} operación(es) · Risk intacto · 0 tokens",
                'data':{'journal_count':int(d.get('paper_learning_journal_count') or 0),'new_trades':len(learning_update.get('added') or []),'risk_authority':False,'live_authority':False},
                'timestamp':datetime.now(timezone.utc).isoformat()
            })
            risk_ok, risk_trace = stonks_agents.SUPERVISOR.risk.precheck(d, clock)
            agent_trace.append(risk_trace)
            _auto_state=stonks_automaton.ensure(d).get('state')
            if _auto_state == 'PAUSED':
                _cycle_now=datetime.now(timezone.utc).isoformat()
                d['engine_last_run']=_cycle_now
                d['engine_last_action']='AUTOMATON PAUSADO · reconciliación/learning activos · sin nuevas entradas'
                d['agent_last_trace']=agent_trace[-30:]
                stonks_automaton.heartbeat(d,'PAUSED',detail=d['engine_last_action'])
                d['market_stream_snapshot']=_stream_status
                _stonks_write(d)
                return {'status':'idle','reason':'Automaton pausado','automaton':True}
            # Shadow is an observation layer, not an execution mode.  In Paper Auto it
            # runs in parallel with the real Paper decision path, but never submits orders.
            # Legacy execution_mode='shadow' remains supported as a shadow-only mode.
            shadow_only = d.get('execution_mode') == 'shadow'
            shadow_observe = shadow_only or (
                d.get('execution_mode') == 'paper_auto'
                and d.get('mode') == 'paper'
                and bool(d.get('autonomous_engine'))
            )
            if shadow_observe:
                try:
                    d, outcome_trace = _stonks_refresh_shadow_outcomes(d)
                    _stonks_write(d)
                    agent_trace.append(outcome_trace)
                except Exception as _outcome_exc:
                    agent_trace.append({'agent':'shadow_outcome','status':'idle','detail':'Outcome Tracker temporalmente no disponible','data':{'error':str(_outcome_exc)[:240],'orders_created':0},'timestamp':datetime.now(timezone.utc).isoformat()})
            if shadow_only:
                shadow_reasons=[]
                if d.get('revoked'): shadow_reasons.append('Control revocado')
                if d.get('paused'): shadow_reasons.append('Motor pausado')
                if d.get('mode')!='paper': shadow_reasons.append('Modo no Paper')
                if not d.get('autonomous_engine'): shadow_reasons.append('Motor autónomo desactivado')
                if not bool(clock.get('is_open')) and not any(_stonks_is_crypto(x) for x in symbols): shadow_reasons.append('Mercado cerrado')
                reason='; '.join(shadow_reasons)
            else:
                reason = stonks_lifecycle.blocked({**d, 'position_lifecycle_enabled':True}, {**clock, 'is_open': bool(clock.get('is_open') or any(_stonks_is_crypto(x) for x in symbols))})
            if reason:
                _cycle_now = datetime.now(timezone.utc).isoformat()
                d['engine_last_run'] = _cycle_now
                d['engine_last_action'] = ('SHADOW · ' if shadow_only else '') + reason
                d['agent_last_trace'] = agent_trace[-30:]
                if shadow_observe:
                    d['shadow_cycle_total'] = int(d.get('shadow_cycle_total') or 0) + 1
                    d['shadow_last_cycle'] = _cycle_now
                    d['shadow_last_reason'] = reason
                    d['shadow_last_market_open'] = bool(clock.get('is_open') or any(_stonks_is_crypto(x) for x in symbols))
                    d['shadow_last_signal_count'] = 0
                d['market_stream_snapshot'] = _stream_status
                _health=_stonks_zero_token_health(d, scope_id)
                d['agent_last_trace'].append({'agent':'data_plane','status':'ok','detail':'Ciclo servido sin IA · caché/event router activos','data':d.get('data_plane_telemetry') or {},'timestamp':_cycle_now})
                d['agent_last_trace'].append({'agent':'self_test','status':'ok' if _health.get('ok') else 'blocked','detail':f"Self-Test {_health.get('passed')}/{_health.get('total')} · 0 tokens",'data':_health,'timestamp':_cycle_now})
                d['agent_last_trace']=d['agent_last_trace'][-30:]
                _stonks_write(d)
                return {'status':'idle', 'reason':reason, 'shadow':shadow_observe}
            open_symbols = {o['symbol'] for o in recon['open_orders']}
            held_symbols = {p['symbol'] for p in recon['positions']}
            records = {r['symbol']:r for r in stonks_lifecycle.active_records(d)}
            open_symbols.update(symbol for symbol in records if symbol not in held_symbols)
            open_symbols.update(d.get('pending_entries', {}))
            actions = list(lifecycle.get('actions') or [])
            shadow_actionable_count = 0
            shadow_wait_count = 0
            for symbol in symbols[:8]:
                symbol=_stonks_symbol_key(symbol)
                symbol_open=bool(_stonks_is_crypto(symbol) or clock.get('is_open'))
                if not symbol_open:
                    actions.append(f"{symbol}: mercado equity cerrado · esperando apertura")
                    continue
                if symbol in open_symbols:
                    actions.append(f"{symbol}: ORDEN ABIERTA · esperando confirmación de Alpaca")
                    continue
                try:
                    if symbol in held_symbols and symbol not in records:
                        actions.append(symbol + ': posición manual; sin gestión automática')
                        continue
                    # Technical features refresh only when a new completed-bar window can exist.
                    _signal_pair, signal_cache = stonks_dataplane.PLANE.signal(
                        scope_id, symbol, strategy, timeframe, symbol_open,
                        lambda sym=symbol: _stonks_current_signal(sym, strategy, timeframe, 'iex'))
                    signal = _signal_pair[0] if isinstance(_signal_pair, tuple) else _signal_pair
                    agent_trace.append(stonks_agents.AgentResult(
                        'analysis','ok',
                        f"{symbol}: {signal.get('signal_label') or signal.get('signal')} · {'cache' if signal_cache.get('cached') else 'barra actualizada'} · 0 tokens",
                        {'symbol':symbol,'signal':signal.get('signal'),'reason':signal.get('reason'),
                         'indicators':signal.get('indicators') or {},'cached':bool(signal_cache.get('cached'))}).as_dict())
                    _dp_event = stonks_dataplane.PLANE.route_event(scope_id, symbol, signal, news_by_symbol.get(symbol) or {})
                    if _dp_event.get('significant'):
                        agent_trace.append({'agent':'event_router','status':'event','detail':f"{symbol}: {_dp_event.get('reason')} · 0 tokens",'data':_dp_event,'timestamp':_dp_event.get('timestamp')})
                    if _dp_event.get('ai_candidate'):
                        agent_trace.append({'agent':'ai_gate','status':'queued','detail':f"{symbol}: candidato a IA bajo demanda; gate cerrado · 0 llamadas",'data':{'model_called':False,'reason':_dp_event.get('reason')},'timestamp':_dp_event.get('timestamp')})
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
                        if shadow_observe:
                            shadow_wait_count += 1
                        actions.append(f"{symbol}: ESPERAR")
                        continue
                    # Shadow observes the same actionable bar in parallel. It evaluates
                    # Decision + Risk with execute=False and therefore has zero broker authority.
                    if shadow_observe:
                        duplicate_shadow = bool(signal.get('bar_time')) and any(
                            all(e.get(k) == v for k, v in {
                                'symbol': symbol, 'strategy': strategy, 'timeframe': timeframe,
                                'signal': signal.get('signal'), 'bar_time': signal['bar_time']}.items())
                            for e in (_stonks_read().get('shadow_log') or []))
                        if not duplicate_shadow:
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
                                'id':uuid.uuid4().hex,'timestamp':datetime.now(timezone.utc).isoformat(),'symbol':symbol,'strategy':strategy,
                                'timeframe':timeframe,'signal':signal.get('signal'),'bar_time':signal.get('bar_time'),'decision':_shadow_data.get('decision'),
                                'primary_reason':_shadow_data.get('primary_reason') or _shadow_data.get('reason'),
                                'price':_shadow_data.get('price'),'estimated_value':_shadow_data.get('estimated_value'),
                                'order_created':False,'outcomes':{},'outcome_status':'pending','outcome_bars':0
                            }
                            latest=_stonks_read(); log=list(latest.get('shadow_log') or []); log.append(_event); latest['shadow_log']=log[-stonks_shadow.MAX_EVENTS:]
                            latest['shadow_outcome_summary']=stonks_shadow.summarize(latest['shadow_log'])
                            latest['shadow_last_run']=_event['timestamp']; latest['shadow_total_signals']=int(latest.get('shadow_total_signals') or 0)+1
                            _stonks_write(latest); _stonks_audit_append('SHADOW_SIGNAL',_event)
                            agent_trace.append({'agent':'shadow_validation','status':'observed','detail':f"{symbol}: {signal.get('signal')} · {_event.get('decision') or 'sin decisión'} · 0 órdenes",'data':_event,'timestamp':_event['timestamp']})
                            actions.append(f"{symbol}: SHADOW {signal.get('signal')} · {_event.get('decision') or 'sin acción'} · 0 órdenes")
                        if shadow_only:
                            continue
                    # v32 Paper Quality Gate: reduce weak/repetitive autonomous entries.
                    # This filter has no broker, sizing, Risk or Live authority.
                    if d.get('paper_profitability_enabled', True):
                        quality = stonks_profitability.evaluate(
                            d, symbol, strategy, timeframe, signal,
                            news_by_symbol.get(symbol) or {}, d.get('paper_learning') or {})
                        latest_quality = _stonks_read()
                        latest_quality['paper_quality_last'] = quality
                        if not quality.get('ok'):
                            stonks_profitability.note_block(latest_quality, quality)
                            _stonks_write(latest_quality)
                            agent_trace.append({'agent':'paper_quality','status':'blocked',
                                'detail':f"{symbol}: calidad {quality.get('quality_score')} · entrada omitida · 0 tokens",
                                'data':quality,'timestamp':quality.get('checked_at')})
                            actions.append(f"{symbol}: QUALITY GATE · {quality.get('quality_score')}/100 · {quality.get('reasons',["entrada filtrada"])[0]}")
                            continue
                        stonks_profitability.note_candidate(latest_quality, quality)
                        _stonks_write(latest_quality)
                        agent_trace.append({'agent':'paper_quality','status':'pass',
                            'detail':f"{symbol}: calidad {quality.get('quality_score')} · candidato Paper · 0 tokens",
                            'data':quality,'timestamp':quality.get('checked_at')})
                    # Reuse the hardened Decision + Risk route so the autonomous Paper path
                    # has exactly the same server-side gates as manual/GUI execution.
                    def _agent_decision(sym, strat, tf, sig):
                        with app.test_request_context('/api/stonks/decision', method='POST', json={
                            'symbol':sym,'strategy':strat,'timeframe':tf,
                            'signal':sig,'execute':True,'manual_confirmed':False,
                            'news_context':news_by_symbol.get(sym) or {}
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
                        latest_entry = _stonks_read()
                        stonks_profitability.note_entry(latest_entry, symbol)
                        _stonks_write(latest_entry)
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
            if shadow_observe:
                d['shadow_cycle_total'] = int(d.get('shadow_cycle_total') or 0) + 1
                d['shadow_last_cycle'] = _cycle_now
                d['shadow_last_market_open'] = bool(clock.get('is_open') or any(_stonks_is_crypto(x) for x in symbols))
                d['shadow_last_signal_count'] = int(shadow_actionable_count)
                d['shadow_last_reason'] = f"Escaneo completado · {shadow_actionable_count} BUY/SELL · {shadow_wait_count} ESPERAR"
            d['market_stream_snapshot'] = _stream_status
            _health=_stonks_zero_token_health(d, scope_id)
            d['agent_last_trace'].append({'agent':'data_plane','status':'ok','detail':'Ciclo 0 tokens · datos en caché + event router','data':d.get('data_plane_telemetry') or {},'timestamp':_cycle_now})
            _feeds=_stream_status.get('feeds') or {}; _connected=sum(1 for x in _feeds.values() if x.get('connected')); _subs=sum(int(x.get('subscriptions') or 0) for x in _feeds.values())
            d['agent_last_trace'].append({'agent':'market_stream','status':'ok' if _connected else 'idle','detail':f'Stream market data · {_connected} feed(s) conectado(s) · {_subs} suscripciones · 0 tokens','data':_stream_status,'timestamp':_cycle_now})
            d['agent_last_trace'].append({'agent':'self_test','status':'ok' if _health.get('ok') else 'blocked','detail':f"Self-Test {_health.get('passed')}/{_health.get('total')} · 0 tokens",'data':_health,'timestamp':_cycle_now})
            d['agent_last_trace']=d['agent_last_trace'][-30:]
            if stonks_automaton.ensure(d).get('state') == 'RUNNING':
                stonks_automaton.complete_cycle(d, action=action, trace=d['agent_last_trace'], learning=d.get('paper_learning') or {})
            _stonks_write(d)
            return {'status':'ok','action':action,'shadow':shadow_observe}
        except Exception as exc:
            d=_stonks_read(); _cycle_now=datetime.now(timezone.utc).isoformat(); d['paper_connected']=False; d['engine_last_run']=_cycle_now; d['engine_last_action']='ERROR · reconciliación Paper no disponible; sin órdenes'
            if d.get('execution_mode') in ('shadow','paper_auto') and d.get('mode') == 'paper' and d.get('autonomous_engine'):
                d['shadow_cycle_total'] = int(d.get('shadow_cycle_total') or 0) + 1
                d['shadow_last_cycle'] = _cycle_now
                d['shadow_last_reason'] = 'ERROR · reconciliación Paper no disponible; 0 órdenes'
                d['shadow_last_signal_count'] = 0
            _stonks_zero_token_health(d, scope_id)
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
        global _STONKS_ENGINE_OWNER_PID
        _STONKS_ENGINE_OWNER_PID = os.getpid()
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
    stonks_dataplane.PLANE.hydrate(_user_scope_id(), d.get('data_plane_telemetry'))
    data_plane=stonks_dataplane.PLANE.status(_user_scope_id(), d.get('data_plane_telemetry'))
    market_stream=_stonks_stream_plan(d)
    self_test=stonks_selftest.run(d, stonks_agents.describe(), data_plane)
    journal_verified = False
    try:
        journal_verified = _stonks_learning_file().is_file() and len(_stonks_learning_read()['journal']) == int(d.get('paper_learning_journal_count') or 0)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        pass
    return jsonify({'ok':True, **d, 'data_plane':data_plane, 'market_stream':market_stream, 'self_test':self_test, 'live_trading_enabled':False, 'readiness':stonks_readiness.evaluate(d, market_stream, self_test, journal_verified), 'paper_profitability':stonks_profitability.public_view(d), 'lifecycle_test':stonks_lifecycle.test_view(d), 'engine_owner':_stonks_engine_owner_read(), 'engine_owned_by_current_user':_stonks_engine_owner_read()==_user_scope_id(), 'audit_count':len(_stonks_audit_read(200)), 'paper_configured': bool(pk and ps), 'crypto_configured': bool(os.environ.get('KRAKEN_API_KEY') and os.environ.get('KRAKEN_API_SECRET')), 'engine_position_count':len(d.get('engine_last_positions') or []), 'engine_open_order_count':len(d.get('engine_last_open_orders') or []), 'position_lifecycle_enabled':bool(d.get('position_lifecycle_enabled')), 'stop_loss_pct':d.get('stop_loss_pct',1.0), 'take_profit_pct':d.get('take_profit_pct',2.0), 'managed_position_count':sum(r.get('status')!='CERRADA' for r in (d.get('managed_positions') or {}).values()), 'lifecycle_last_action':d.get('lifecycle_last_action'), 'agents':stonks_agents.describe(), 'automaton':stonks_automaton.public_view(d)})

@app.get('/api/stonks/agents')
def stonks_agents_api():
    d=_stonks_read()
    return jsonify({'ok':True,'paper':True, **stonks_agents.describe(), 'last_trace':d.get('agent_last_trace') or []})

@app.get('/api/stonks/dataplane')
def stonks_dataplane_api():
    d=_stonks_read()
    return jsonify({'ok':True,'paper':True,'zero_token':True,'data_plane':stonks_dataplane.PLANE.status(_user_scope_id(), d.get('data_plane_telemetry'))})

@app.get('/api/stonks/stream')
def stonks_stream_api():
    d=_stonks_read()
    return jsonify({'ok':True,'zero_token':True,'stream':_stonks_stream_plan(d)})

@app.post('/api/stonks/stream/watchlist')
@_stonks_serialized
def stonks_stream_watchlist_api():
    payload=request.get_json(silent=True) or {}; d=_stonks_read()
    def parse(raw, kind):
        rows=[]
        values=raw if isinstance(raw,list) else str(raw or '').split(',')
        for item in values:
            s=str(item or '').strip().upper()
            if kind=='crypto': s=s.replace('-', '/')
            if s and s not in rows: rows.append(s)
        return rows
    eq=parse(payload.get('equities', d.get('stream_watchlist_equities')), 'equities')[:30]
    cr=parse(payload.get('crypto', d.get('stream_watchlist_crypto')), 'crypto')[:20]
    op=parse(payload.get('options', d.get('stream_watchlist_options')), 'options')[:20]
    for s in eq:
        if '/' in s or len(s)>24 or not s.replace('.','').replace('-','').isalnum():
            return jsonify({'ok':False,'error':f'Símbolo equity/ETF no válido: {s}'}),400
    for s in cr:
        if '/' not in s or len(s)>24:
            return jsonify({'ok':False,'error':f'Par crypto no válido: {s}'}),400
    for s in op:
        if len(s)>32 or not s.isalnum():
            return jsonify({'ok':False,'error':f'Contrato de opción no válido: {s}'}),400
    d['stream_watchlist_equities']=eq; d['stream_watchlist_crypto']=cr; d['stream_watchlist_options']=op
    _stonks_write(d)
    stream=_stonks_stream_plan(d)
    stream['watchlist']={'equities':eq,'crypto':cr,'options':op}
    _stonks_audit_append('MARKET STREAM',{'equities':eq,'crypto':cr,'options':op,'orders_created':0,'token_cost':0})
    return jsonify({'ok':True,'stream':stream,'watchlist':stream.get('watchlist'),'orders_created':0,'token_cost':0})

@app.get('/api/stonks/selftest')
def stonks_selftest_api():
    d=_stonks_read()
    stonks_dataplane.PLANE.hydrate(_user_scope_id(), d.get('data_plane_telemetry'))
    telemetry=stonks_dataplane.PLANE.status(_user_scope_id(), d.get('data_plane_telemetry'))
    return jsonify({'ok':True,'paper':True,'self_test':stonks_selftest.run(d, stonks_agents.describe(), telemetry)})

@app.get('/api/stonks/news')
def stonks_news_api():
    symbol=re.sub(r'[^A-Za-z0-9.\-]', '', request.args.get('symbol','AAPL').upper())[:16]
    force=request.args.get('force','0') in ('1','true','yes')
    data=stonks_news.get_context(symbol, force=force)
    return jsonify(data)

# --- ZAR Holdings / subcompanies -------------------------------------------------
from . import business_orchestration
business_orchestration.register(app, _user_scope_id)
from . import business_workflows
from .site_projects import preview_headers as site_projects_preview
business_workflows.register(app, _user_scope_id)
from . import agency_events
agency_events.register(app)

@app.get('/api/holdings/state')
def holdings_state_api():
    scope=_user_scope_id()
    view=holdings.public_view(scope)
    try:
        sd=_stonks_read(); sa=stonks_automaton.public_view(sd)
        view['stonks']={
            'paper_only':True,'automaton_state':sa.get('state'),'pnl_usd':sa.get('pnl_usd',0),
            'trades':sa.get('trades',0),'win_rate':sa.get('win_rate',0),
            'equity':(sd.get('account') or {}).get('equity') or (sd.get('engine_last_account') or {}).get('equity')
        }
    except Exception as exc:
        view['stonks']={'paper_only':True,'error':str(exc)[:240]}
    view['connectors']={
        'jev':jev_decision.status(), 'voice':voice_pro.status(), 'commerce':commerce_company.status(),
        'media':media_company.status(), 'agency':web_agency.status(), 'sites':sites_company.status(), 'social':social_publish.status(),
    }
    return jsonify({'ok':True, **view})

@app.post('/api/holdings/company/<company>/<action>')
def holdings_company_action_api(company, action):
    try:
        d=holdings.set_company_state(_user_scope_id(), company, action)
        return jsonify({'ok':True,'company':d['companies'][company]})
    except Exception as exc:
        return jsonify({'ok':False,'error':str(exc)}),400

@app.post('/api/holdings/global-stop')
def holdings_global_stop_api():
    data=request.get_json(silent=True) or {}
    try:
        d=holdings.set_global_stop(_user_scope_id(), bool(data.get('enabled',True)), data.get('reason') or '')
        return jsonify({'ok':True,'global_stop':d['global_stop'],'state':holdings.public_view(_user_scope_id())})
    except Exception as exc:
        return jsonify({'ok':False,'error':str(exc)}),400

@app.post('/api/holdings/cycle')
def holdings_cycle_api():
    try: return jsonify(company_runtime.cycle_scope(_user_scope_id()))
    except Exception as exc: return jsonify({'ok':False,'error':str(exc)}),400

@app.post('/api/holdings/ledger')
def holdings_ledger_api():
    data=request.get_json(silent=True) or {}
    try:
        row=holdings.add_ledger(_user_scope_id(), data.get('company'), data.get('kind') or 'revenue', data.get('amount') or 0,
            currency=data.get('currency') or 'EUR', status=data.get('status') or 'collected', source=data.get('source') or 'manual',
            reference=data.get('reference') or '', note=data.get('note') or '', verified=bool(data.get('verified')))
        return jsonify({'ok':True,'row':row,'state':holdings.public_view(_user_scope_id())})
    except Exception as exc: return jsonify({'ok':False,'error':str(exc)}),400

@app.post('/api/holdings/jev/test')
def holdings_jev_test_api():
    data=request.get_json(silent=True) or {}
    state=data.get('state') or {'action':'Publicar una demo comercial y enviar un email','amount_eur':490}
    try:
        result=jev_decision.gate('Prueba ZAR Holdings',state,data.get('risk') or 'medium')
        return jsonify({'ok':True,'result':result,'status':jev_decision.status()})
    except Exception as exc: return jsonify({'ok':False,'error':str(exc)}),400

@app.get('/api/holdings/voice/status')
def holdings_voice_status_api(): return jsonify({'ok':True, **voice_pro.status()})

@app.post('/api/holdings/commerce/sync')
def holdings_commerce_sync_api():
    try: return jsonify(commerce_company.sync_paid_orders(_user_scope_id()))
    except Exception as exc: return jsonify({'ok':False,'error':str(exc)}),400

@app.post('/api/holdings/commerce/scout')
def holdings_commerce_scout_api():
    data=request.get_json(silent=True) or {}
    try: return jsonify(commerce_company.scout(_user_scope_id(),data.get('query'),data.get('sale_price') or 0))
    except Exception as exc: return jsonify({'ok':False,'error':str(exc)}),400

@app.post('/api/holdings/commerce/product')
def holdings_commerce_product_api():
    data=request.get_json(silent=True) or {}
    try: return jsonify(commerce_company.create_draft_product(_user_scope_id(), data))
    except Exception as exc: return jsonify({'ok':False,'error':str(exc)}),400

@app.post('/api/holdings/commerce/supplier-order')
def holdings_commerce_supplier_order_api():
    data=request.get_json(silent=True) or {}
    try: return jsonify(commerce_company.supplier_order(data.get('order') or {},confirmed=bool(data.get('confirmed'))))
    except Exception as exc: return jsonify({'ok':False,'error':str(exc)}),400

@app.get('/api/holdings/media/jobs')
def holdings_media_jobs_api():
    return jsonify(media_company.jobs(_user_scope_id()))

@app.get('/api/holdings/media/video/<task_id>')
def holdings_media_video_api(task_id):
    try:
        path = media_company.video_path(_user_scope_id(), task_id)
        return send_file(path, mimetype='video/mp4', conditional=True, max_age=0)
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 404

@app.get('/media-public/<token>.mp4')
def holdings_media_public_video_api(token):
    # Narrow bearer link for platform ingestion; no DramaClaw credential reaches a browser.
    from itsdangerous import URLSafeTimedSerializer, BadSignature
    try:
        data = URLSafeTimedSerializer(app.secret_key, salt='media-export-v1').loads(token, max_age=86400)
        record = media_company._read(data['scope'], data['task'])
        if (record.get('checkpoint') or {}).get('project_id') != data['project']:
            raise ValueError('Export caducado')
        path = media_company.video_path(data['scope'], data['task'])
        return send_file(path, mimetype='video/mp4', conditional=True, max_age=0)
    except (BadSignature, ValueError, KeyError, TypeError):
        return jsonify({'ok': False, 'error': 'Export no disponible.'}), 404

@app.post('/api/holdings/media/queue')
def holdings_media_queue_api():
    data=request.get_json(silent=True) or {}
    try:
        task=media_company.queue_story(_user_scope_id(),data.get('topic'),data.get('goal') or 'retención',data.get('platform') or 'tiktok')
        return jsonify({'ok':True,'task':task})
    except Exception as exc: return jsonify({'ok':False,'error':str(exc)}),400

@app.post('/api/holdings/media/produce')
def holdings_media_produce_api():
    data=request.get_json(silent=True) or {}
    try: return jsonify(media_company.produce_local(_user_scope_id(),data.get('task_id')))
    except Exception as exc: return jsonify({'ok':False,'error':str(exc)}),400

@app.post('/api/holdings/media/edit')
def holdings_media_edit_api():
    data=request.get_json(silent=True) or {}
    try: return jsonify(media_company.edit_story(_user_scope_id(),data.get('task_id'),data.get('notes') or ''))
    except Exception as exc: return jsonify({'ok':False,'error':str(exc)}),400

@app.post('/api/holdings/media/publish')
def holdings_media_publish_api():
    data=request.get_json(silent=True) or {}
    try:
        from itsdangerous import URLSafeTimedSerializer
        from flask import url_for
        scope = _user_scope_id()
        task_id = data.get('task_id')
        confirmed = data.get('confirmed') is True
        video_url = ''
        if confirmed:
            media_company.video_path(scope, task_id)
            record = media_company._read(scope, task_id)
            token = URLSafeTimedSerializer(app.secret_key, salt='media-export-v1').dumps({
                'scope': scope, 'task': task_id, 'project': record['checkpoint']['project_id']})
            video_url = url_for('holdings_media_public_video_api', token=token, _external=True)
        return jsonify(media_company.publish(scope, task_id, video_url, data.get('platform'),
                       data.get('caption') or '', confirmed=confirmed))
    except (ValueError, KeyError) as exc: return jsonify({'ok':False,'error':str(exc)}),400
    except Exception: return jsonify({'ok':False,'error':'Publicación Media no disponible.'}),400

@app.post('/api/holdings/agency/discover')
def holdings_agency_discover_api():
    data=request.get_json(silent=True) or {}
    try: return jsonify(web_agency.discover(_user_scope_id(),data.get('query'),data.get('max_results') or 10))
    except Exception as exc: return jsonify({'ok':False,'error':str(exc)}),400

@app.post('/api/holdings/agency/demo')
def holdings_agency_demo_api():
    data=request.get_json(silent=True) or {}
    try: return jsonify({'ok':True,'demo':web_agency.build_demo(_user_scope_id(),data.get('lead') or {},data.get('price_eur') or 490)})
    except Exception as exc: return jsonify({'ok':False,'error':str(exc)}),400

@app.post('/api/holdings/agency/outreach')
def holdings_agency_outreach_api():
    data=request.get_json(silent=True) or {}
    try: return jsonify(web_agency.prepare_outreach(_user_scope_id(),data.get('lead') or {},data.get('demo_url') or '',data.get('price_eur') or 490))
    except Exception as exc: return jsonify({'ok':False,'error':str(exc)}),400

@app.post('/api/holdings/agency/email')
def holdings_agency_email_api():
    data=request.get_json(silent=True) or {}
    try: return jsonify(web_agency.find_contact_email(data.get('lead') or {}))
    except Exception as exc: return jsonify({'ok':False,'error':str(exc)}),400

@app.post('/api/holdings/agency/draft')
def holdings_agency_draft_api():
    data=request.get_json(silent=True) or {}
    try: return jsonify(web_agency.create_outreach_draft(_user_scope_id(),data.get('lead') or {},data.get('demo_url') or '',data.get('email') or '',data.get('price_eur') or 490))
    except Exception as exc: return jsonify({'ok':False,'error':str(exc)}),400

@app.post('/api/holdings/agency/negotiate')
def holdings_agency_negotiate_api():
    data=request.get_json(silent=True) or {}
    try: return jsonify({'ok':True, **web_agency.negotiate(data.get('current_price') or 490,data.get('message') or '',data.get('floor_price') or 350,data.get('max_discount_pct') or 15)})
    except Exception as exc: return jsonify({'ok':False,'error':str(exc)}),400

@app.get('/api/holdings/sites')
def holdings_sites_list_api():
    try: return jsonify({'ok':True,'sites':sites_company.list_sites(_user_scope_id()),'status':sites_company.status()})
    except Exception as exc: return jsonify({'ok':False,'error':str(exc)}),400

@app.post('/api/holdings/sites/ideas')
def holdings_sites_ideas_api():
    data=request.get_json(silent=True) or {}
    try: return jsonify(sites_company.scout_ideas(data.get('seed') or data.get('topic') or 'ideas útiles España',data.get('limit') or 6))
    except Exception as exc: return jsonify({'ok':False,'error':str(exc)}),400

@app.post('/api/holdings/sites/create')
def holdings_sites_create_api():
    data=request.get_json(silent=True) or {}
    try:
        if data.get('queue'):
            task=sites_company.queue_site(_user_scope_id(),data.get('topic'),data.get('name') or '')
            return jsonify({'ok':True,'queued':True,'task':task})
        return jsonify({'ok':True,'site':sites_company.build_site(_user_scope_id(),data.get('topic'),data.get('name') or '',queue_promotion=bool(data.get('queue_promotion',True)))})
    except Exception as exc: return jsonify({'ok':False,'error':str(exc)}),400

@app.post('/api/holdings/sites/deploy')
def holdings_sites_deploy_api():
    data=request.get_json(silent=True) or {}
    try: return jsonify(sites_company.deploy_vercel(_user_scope_id(),data.get('slug') or ''))
    except Exception as exc: return jsonify({'ok':False,'error':str(exc)}),400

@app.post('/api/holdings/sites/domains/search')
def holdings_sites_domain_search_api():
    data=request.get_json(silent=True) or {}
    names=data.get('domains') or ([data.get('domain')] if data.get('domain') else [])
    try: return jsonify(sites_company.search_domains(names))
    except Exception as exc: return jsonify({'ok':False,'error':str(exc)}),400

@app.post('/api/holdings/sites/domains/policy')
def holdings_sites_domain_policy_api():
    data=request.get_json(silent=True) or {}
    try:
        d=sites_company.configure_policy(
            _user_scope_id(),
            allow_domain_reinvestment=data.get('allow_domain_reinvestment'),
            max_domain_eur=data.get('max_domain_eur'),
            auto_domain_purchase=data.get('auto_domain_purchase'),
            domain_daily_budget_eur=data.get('domain_daily_budget_eur'),
        )
        return jsonify({'ok':True,'company':d['companies']['sites']})
    except Exception as exc: return jsonify({'ok':False,'error':str(exc)}),400

@app.post('/api/holdings/sites/network')
def holdings_sites_network_api():
    data=request.get_json(silent=True) or {}
    try:
        d=sites_company.configure_network(
            _user_scope_id(),
            enabled=bool(data.get('enabled', True)),
            seed_topic=data.get('seed_topic'),
            max_sites=data.get('max_sites', 12),
            auto_deploy_vercel=data.get('auto_deploy_vercel', True),
            allow_domain_reinvestment=data.get('allow_domain_reinvestment', False),
            auto_domain_purchase=data.get('auto_domain_purchase', False),
            max_domain_eur=data.get('max_domain_eur', 20),
            domain_daily_budget_eur=data.get('domain_daily_budget_eur', 40),
        )
        return jsonify({'ok':True,'company':d['companies']['sites'],'sites':sites_company.list_sites(_user_scope_id())})
    except Exception as exc: return jsonify({'ok':False,'error':str(exc)}),400

@app.post('/api/holdings/sites/domains/buy')
def holdings_sites_domain_buy_api():
    data=request.get_json(silent=True) or {}
    try: return jsonify(sites_company.buy_domain(_user_scope_id(),data.get('slug') or '',data.get('domain') or '',data.get('expected_price') or 0,confirmed=bool(data.get('confirmed'))))
    except Exception as exc: return jsonify({'ok':False,'error':str(exc)}),400

@app.post('/api/holdings/sites/adsense/sync')
def holdings_sites_adsense_sync_api():
    try: return jsonify(sites_company.sync_adsense(_user_scope_id()))
    except Exception as exc: return jsonify({'ok':False,'error':str(exc)}),400

@app.get('/holdings/demo/<slug>/')
def holdings_demo_page(slug):
    safe=re.sub(r'[^a-zA-Z0-9_-]+','',slug)[:80]
    if safe != slug: return 'Demo no válida',400
    path=Path(os.environ.get('ZAR_DATA_DIR','/data'))/'holdings_public_demos'/safe/'index.html'
    if not path.exists(): return 'Demo no encontrada',404
    return send_file(path, mimetype='text/html')

@app.get('/holdings/site/<slug>/')
def holdings_site_page(slug):
    safe=re.sub(r'[^a-zA-Z0-9_-]+','',slug)[:80]
    if safe != slug: return 'Sitio no válido',400
    path=Path(os.environ.get('ZAR_DATA_DIR','/data'))/'holdings_public_sites'/safe/'index.html'
    if not path.exists(): return 'Sitio no encontrado',404
    return site_projects_preview(send_file(path,mimetype='text/html'))

@app.get('/holdings/site/<slug>/<path:filename>')
def holdings_site_asset(slug,filename):
    safe=re.sub(r'[^a-zA-Z0-9_-]+','',slug)[:80]
    if safe != slug or '..' in filename or filename.startswith('/') or '\\' in filename: return 'Ruta no válida',400
    root=(Path(os.environ.get('ZAR_DATA_DIR','/data'))/'holdings_public_sites'/safe).resolve()
    path=(root/filename).resolve()
    if root not in path.parents and path != root: return 'Ruta no válida',400
    if not path.exists() or not path.is_file(): return 'Archivo no encontrado',404
    return site_projects_preview(send_file(path))

@app.get('/api/subagents/state')
def subagents_state_api():
    base=subagent_orchestrator.describe_general_agents()
    d=_stonks_read()
    st=stonks_agents.describe()
    # Orchestration is an observational UI. Refresh the broker clock here so
    # Market Data never displays a stale persisted state when the autonomous
    # engine is paused/off. This does not authorize or submit any order.
    trace=list(d.get('agent_last_trace') or [])
    trace=[row for row in trace if row.get('agent') != 'market_data']
    try:
        fresh_clock=_stonks_market_clock_snapshot()
        trace.append({
            'agent':'market_data', 'status':'ok',
            'detail':'Reloj de mercado actualizado directamente desde Alpaca Paper · 0 órdenes',
            'data':{
                'positions':len(d.get('engine_last_positions') or []),
                'open_orders':len(d.get('engine_last_open_orders') or []),
                'market_open':fresh_clock.get('is_open'),
                'clock_timestamp':fresh_clock.get('timestamp'),
                'clock_received_at':fresh_clock.get('received_at'),
                'clock_age_seconds':fresh_clock.get('age_seconds'),
                'clock_source':fresh_clock.get('source'),
                'order_authority':False,
            },
            'timestamp':fresh_clock.get('received_at'),
        })
    except Exception as exc:
        trace.append({
            'agent':'market_data', 'status':'idle',
            'detail':'Reloj de mercado no disponible; no se asume mercado cerrado',
            'data':{'market_open':None,'error':str(exc)[:240],'order_authority':False},
            'timestamp':datetime.now(timezone.utc).isoformat(),
        })
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
        'stonks_trace':trace,
        'stonks_phase':st.get('phase'),
        'stonks_paper_only':True,
        'active_count':len([x for x in trace[-10:] if x.get('status') not in ('idle','no_action')]),
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
    symbol=_stonks_symbol_key(request.args.get('symbol') or 'AAPL')
    if not symbol or len(symbol)>24 or not symbol.replace('.','').replace('-','').replace('/','').isalnum():
        return jsonify({'ok':False,'error':'Símbolo no válido.'}),400
    try:
        if _stonks_is_crypto(symbol):
            key=symbol.replace('/','')
            encoded=urlquote(symbol, safe='')
            clock=_stonks_crypto_clock()
            trade=None; snapshot=None; trade_error=None; snapshot_error=None
            try:
                raw=_alpaca_market_request(f'/v1beta3/crypto/us/latest/trades?symbols={encoded}')
                trade=(raw.get('trades') or {}).get(symbol) or (raw.get('trades') or {}).get(key)
            except Exception as exc:
                trade_error=str(exc)
            if not trade:
                try:
                    raw=_alpaca_market_request(f'/v1beta3/crypto/us/snapshots?symbols={encoded}')
                    snapshot=(raw.get('snapshots') or {}).get(symbol) or (raw.get('snapshots') or {}).get(key)
                except Exception as exc:
                    snapshot_error=str(exc)
            latest_trade=trade or (snapshot or {}).get('latestTrade')
            latest_quote=(snapshot or {}).get('latestQuote')
            daily_bar=(snapshot or {}).get('dailyBar')
            return jsonify({'ok':True,'symbol':symbol,'asset_class':'crypto','market':clock,
                'quote':latest_quote,'trade':latest_trade,'daily_bar':daily_bar,
                'source':'trade' if trade else ('snapshot' if snapshot else None),
                'diagnostics':{'trade_error':trade_error,'snapshot_error':snapshot_error}})

        clock=_stonks_market_clock_snapshot(); is_open=bool(clock.get('is_open'))
        quote=None; trade=None; snapshot=None; quote_error=None; trade_error=None; snapshot_error=None
        try:
            q=_alpaca_market_request(f'/v2/stocks/{symbol}/quotes/latest'); quote=(q.get('quotes') or {}).get(symbol)
        except Exception as exc: quote_error=str(exc)
        if not quote:
            try:
                t=_alpaca_market_request(f'/v2/stocks/{symbol}/trades/latest'); trade=(t.get('trades') or {}).get(symbol)
            except Exception as exc: trade_error=str(exc)
        if not quote and not trade:
            try: snapshot=_alpaca_market_request(f'/v2/stocks/{symbol}/snapshot')
            except Exception as exc: snapshot_error=str(exc)
        latest_trade=trade or (snapshot or {}).get('latestTrade'); latest_quote=quote or (snapshot or {}).get('latestQuote'); daily_bar=(snapshot or {}).get('dailyBar')
        return jsonify({'ok':True,'symbol':symbol,'asset_class':'equity','market':{'is_open':is_open,'timestamp':clock.get('timestamp'),'next_open':clock.get('next_open'),'next_close':clock.get('next_close')},'quote':latest_quote,'trade':latest_trade,'daily_bar':daily_bar,'source':'quote' if quote else ('trade' if trade else ('snapshot' if snapshot else None)),'diagnostics':{'quote_error':quote_error,'trade_error':trade_error,'snapshot_error':snapshot_error}})
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
    symbol=_stonks_symbol_key(symbol or 'AAPL')
    timeframe=str(timeframe or '1Min').strip()
    strategy=str(strategy or 'trend').strip().lower()
    feed=str(feed or 'iex').strip().lower()
    if timeframe not in ('1Min','5Min','15Min'):
        timeframe='1Min'
    if strategy not in ('trend','mean_reversion'):
        strategy='trend'
    if feed not in ('iex','sip'):
        feed='iex'
    crypto=_stonks_is_crypto(symbol)
    clock=_stonks_crypto_clock() if crypto else _stonks_market_clock_snapshot()
    end=datetime.now(timezone.utc)
    from datetime import timedelta
    # Crypto is 24/7; use a wider lookback so 55 completed bars are available even
    # when equity RTH is closed.
    start=end-timedelta(hours=12 if timeframe=='1Min' else 36)
    params={
        'symbols':symbol,'timeframe':timeframe,
        'start':start.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'end':end.strftime('%Y-%m-%dT%H:%M:%SZ'),'limit':1000,
        'sort':'asc'
    }
    if crypto:
        data=_alpaca_market_request('/v1beta3/crypto/us/bars',params=params)
    else:
        params['feed']=feed
        data=_alpaca_market_request('/v2/stocks/bars',params=params)
    raw=((data.get('bars') or {}).get(symbol) or (data.get('bars') or {}).get(symbol.replace('/',''))) if isinstance(data,dict) else []
    raw=raw if isinstance(raw,list) else []
    bars=[]
    for b in raw:
        try:
            ts=datetime.fromisoformat(str(b.get('t','')).replace('Z','+00:00'))
            if ts.tzinfo is None or ts + timedelta(minutes=int(timeframe[:-3])) > end: continue
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
    bar_time=item.get('bar_time')
    age=(end-datetime.fromisoformat(bar_time.replace('Z','+00:00'))).total_seconds() if bar_time else None
    item.update(asset=symbol,direction=item['signal'],confidence=None,entry=item.get('price'),
                stop_loss=None,take_profit=None,expected_risk=None,expected_reward=None,risk_reward_ratio=None,
                evidence=[item['reason']],timestamp=end.isoformat(),
                data_freshness={'source':'Alpaca crypto' if crypto else 'Alpaca '+feed,
                                'state':'DELAYED' if age is not None else 'UNKNOWN',
                                'last_update':bar_time,'age_seconds':age,'note':'Completed historical bars; not a realtime quote'})
    return item, clock

@app.get('/api/stonks/signals')
def stonks_signals_api():
    """Calculate near-real-time signals from completed Alpaca bars. Analysis only."""
    try:
        raw_symbols=str(request.args.get('symbols') or 'AAPL')
        symbols=[]
        for raw in raw_symbols.split(','):
            symbol=_stonks_symbol_key(raw)
            if symbol and symbol not in symbols: symbols.append(symbol)
        if not symbols: symbols=['AAPL']
        if len(symbols)>8: return jsonify({'ok':False,'error':'Máximo 8 símbolos por análisis.'}),400
        for symbol in symbols:
            if len(symbol)>24 or not symbol.replace('.','').replace('-','').replace('/','').isalnum():
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
        if not symbol or len(symbol)>24 or not symbol.replace('.','').replace('-','').replace('/','').isalnum():
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
        order=_stonks_submit_paper_order(body)
        _stonks_audit_append('TEST_PAPER',{'symbol':symbol,'decision':'ORDEN_ENVIADA','side':'buy','qty':qty,'estimated_value':order_value,'order_id':order.get('id'),'status':order.get('status')})
        return jsonify({'ok':True,'paper':True,'order_created':True,'test':True,'symbol':symbol,'qty':qty,'estimated_value':order_value,'order':order})
    except Exception as exc:
        return jsonify({'ok':False,'paper':True,'error':str(exc)}),502

@app.get('/api/stonks/audit')
def stonks_audit_api():
    return jsonify({'ok':True,'paper':True,'audit':list(reversed(_stonks_audit_read(100)))})

@app.get('/api/stonks/learning')
@_stonks_serialized
def stonks_learning_api():
    d=_stonks_read()
    if d.get('paper_learning_enabled', True):
        update=_stonks_learning_update_state(d)
        if update.get('added'):
            _stonks_write(d)
    store=_stonks_learning_read(); view_state=dict(d); view_state['paper_learning_journal']=store.get('journal') or []
    return jsonify({'ok':True,'zero_tokens':True,'learning':stonks_learning.public_view(view_state, limit=30)})

@app.post('/api/stonks/decision')
@_stonks_serialized
def stonks_decision_api(engine=False, lifecycle_test=False):
    """Evaluate one current signal against ZAR Risk and optionally execute Paper.
    Live trading is intentionally impossible in this endpoint."""
    try:
        payload=request.get_json(silent=True) or {}
        symbol=_stonks_symbol_key(payload.get('symbol') or '')
        strategy=str(payload.get('strategy') or 'trend').strip().lower()
        timeframe=str(payload.get('timeframe') or '1Min').strip()
        requested_signal=str(payload.get('signal') or '').strip().upper()
        execute=bool(payload.get('execute'))
        manual_confirmed=bool(payload.get('manual_confirmed'))
        if not symbol or len(symbol)>24 or not symbol.replace('.','').replace('-','').replace('/','').isalnum():
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
        if execute:
            add_check('SHADOW','Shadow no permite enviar órdenes',d.get('execution_mode')!='shadow')
        add_check('MARKET','Mercado cerrado',bool(_stonks_is_crypto(symbol) or clock.get('is_open')))
        if lifecycle_test:
            add_check('LIFECYCLE', 'Gestión de posición desactivada', bool(d.get('position_lifecycle_enabled')))
            add_check('AUTO', 'Modo Paper automático requerido', d.get('execution_mode')=='paper_auto')
            add_check('SINGLE_TEST', 'Ya existe una prueba activa', not any(r.get('purpose')=='TEST_LIFECYCLE' for r in stonks_lifecycle.active_records(d)))


        account=_alpaca_paper_request('/v2/account')
        equity=float(stonks_lifecycle.number(account.get('equity'))); last_equity=float(stonks_lifecycle.number(account.get('last_equity')))
        add_check('ACCOUNT_ACTIVE','Cuenta Paper no operativa', account.get('status')=='ACTIVE' and not (account.get('trading_blocked') or account.get('account_blocked')))
        add_check('ACCOUNT_EQUITY','Capital Paper no valido',equity>0)
        if lifecycle_test:
            equity = float(stonks_lifecycle.number(account.get('equity')))
            last_equity = float(stonks_lifecycle.number(account.get('last_equity')))
            for field in ['max_trade_eur','max_position_pct','max_daily_loss_eur']:
                stonks_lifecycle.number(d[field])
            add_check('EQUITY', 'Capital Paper no válido para una prueba', equity>0)
            add_check('CONNECTED', 'Alpaca Paper no está disponible para operar', account.get('status')=='ACTIVE' and not (account.get('trading_blocked') or account.get('account_blocked')))
            add_check('BUYING_POWER', 'Saldo Paper insuficiente para 1 USD', float(account.get('buying_power') or 0)>=1)
            asset = _alpaca_paper_request(_stonks_asset_path(symbol))
            add_check('FRACTIONABLE', 'Activo no compatible con prueba mínima Paper', asset.get('status')=='active' and asset.get('tradable') is True and asset.get('fractionable') is True and asset.get('class')=='us_equity')

        daily_loss=max(0.0,last_equity-equity); max_daily=float(d.get('max_daily_loss_eur',10))
        add_check('DAILY_LOSS','Pérdida diaria límite alcanzada',not (daily_loss>=max_daily),f'{daily_loss:.2f} USD / límite {max_daily:.2f} USD')

        positions=_alpaca_paper_request('/v2/positions')
        if not isinstance(positions,list):
            raise RuntimeError('Snapshot de posiciones Paper no válido')
        positions=[_stonks_normalize_broker_row(x) for x in positions]
        current=next((p for p in positions if _stonks_symbol_key(p.get('symbol'))==symbol),None)
        if engine:
            add_check('ENGINE_OWNER', 'Motor no autorizado', d.get('autonomous_engine') and _stonks_engine_owner_read()==_user_scope_id())
            add_check('FLAT_BASELINE', 'El motor solo abre símbolos sin posición previa', current is None)
            add_check('OWNERSHIP_PENDING', 'Hay una intención ZAR pendiente de reconciliar',
                      not any(r['symbol']==symbol for r in stonks_lifecycle.active_records(d)))


        # Stocks and crypto use separate Alpaca market-data endpoints.
        last, _price_clock = _stonks_latest_price(symbol)
        price=float(stonks_lifecycle.number(last.get('p') or 0))
        try:
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(str(last.get('t')).replace('Z','+00:00'))).total_seconds()
            fresh=-5 <= age <= 120
        except (ValueError, TypeError):
            fresh=False
        add_check('PRICE_FRESH','Precio desactualizado o no verificable',fresh)
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
            open_orders=[_stonks_normalize_broker_row(x) for x in open_orders]
            same_symbol=[o for o in open_orders if _stonks_symbol_key(o.get('symbol'))==symbol]
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
            body={'symbol':symbol,'qty':str(qty),'side':'buy' if requested_signal=='BUY' else 'sell','type':'market','time_in_force':'gtc' if _stonks_is_crypto(symbol) else 'day'}
            if engine:
                intent = stonks_lifecycle.entry_intent(d, symbol, body['side'], qty, strategy, timeframe)
                if not lifecycle_test:
                    intent['decision_context'] = stonks_learning.decision_context(
                        actual, payload.get('news_context') if isinstance(payload.get('news_context'), dict) else {},
                        decision, primary_reason)
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
            order=_stonks_submit_paper_order(body)
            d['last_executed_signals'][key]=datetime.now(timezone.utc).isoformat()
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




def _stonks_orphan_test_snapshot():
    owner=_stonks_engine_owner_read(); me=_user_scope_id()
    if not owner or owner==me:
        return {'ok':True,'available':False,'reason':'No hay owner anterior distinto.'}
    with app.test_request_context('/api/stonks/orphan-test/inspect'):
        session['zar_user_id']=owner
        previous=_stonks_read()
    tests=[r for r in stonks_lifecycle.active_records(previous) if r.get('purpose')=='TEST_LIFECYCLE']
    non_tests=[r for r in stonks_lifecycle.active_records(previous) if r.get('purpose')!='TEST_LIFECYCLE']
    positions=_alpaca_paper_request('/v2/positions')
    orders=_alpaca_paper_request('/v2/orders', params={'status':'open','limit':500,'nested':'false'})
    if not isinstance(positions,list) or not isinstance(orders,list):
        raise RuntimeError('No se pudo verificar la exposición Alpaca Paper.')
    if len(tests)!=1 or non_tests or len(positions)!=1 or orders:
        return {'ok':True,'available':False,'owner':owner,'test_count':len(tests),'other_records':len(non_tests),
                'positions':len(positions),'orders':len(orders),'reason':'La exposición no coincide con una única prueba Paper huérfana.'}
    record=tests[0]; pos=positions[0]
    if str(pos.get('symbol','')).upper()!=str(record.get('symbol','')).upper() or float(pos.get('qty') or 0)<=0:
        return {'ok':True,'available':False,'owner':owner,'positions':1,'orders':0,'reason':'La posición abierta no coincide con la prueba registrada.'}
    return {'ok':True,'available':True,'owner':owner,'record_id':record.get('id'),'symbol':pos.get('symbol'),
            'qty':pos.get('qty'),'market_value':pos.get('market_value'),'avg_entry_price':pos.get('avg_entry_price')}

@app.get('/api/stonks/orphan-test')
@_stonks_serialized
def stonks_orphan_test_api():
    try:
        return jsonify(_stonks_orphan_test_snapshot())
    except Exception as exc:
        return jsonify({'ok':False,'available':False,'error':str(exc)}),502

@app.post('/api/stonks/orphan-test/close')
@_stonks_serialized
def stonks_orphan_test_close_api():
    payload=request.get_json(silent=True) or {}
    if payload.get('confirm') is not True:
        return jsonify({'ok':False,'error':'Hace falta confirmación explícita para cerrar la prueba Paper.'}),400
    snap=_stonks_orphan_test_snapshot()
    if not snap.get('available'):
        return jsonify({'ok':False,'error':snap.get('reason') or 'No hay una prueba Paper huérfana cerrable.'}),409
    account=_alpaca_paper_request('/v2/account')
    if account.get('status')!='ACTIVE' or account.get('trading_blocked') or account.get('account_blocked'):
        return jsonify({'ok':False,'error':'La cuenta Alpaca Paper no está operativa.'}),409
    cid=('zar-orphan-test-close-'+uuid.uuid4().hex[:18])[:48]
    body={'symbol':_stonks_symbol_key(snap['symbol']),'qty':str(snap['qty']),'side':'sell','type':'market','time_in_force':'gtc' if _stonks_is_crypto(snap['symbol']) else 'day','client_order_id':cid}
    try:
        data=_stonks_submit_paper_order(body)
    except (RuntimeError, requests.RequestException, ValueError):
        return jsonify({'ok':False,'error':'Alpaca Paper no confirmó el cierre de la prueba.'}),502
    _stonks_audit_append('ORPHAN_TEST_CLOSE',{'paper':True,'symbol':snap['symbol'],'qty':snap['qty'],'order_id':data.get('id'),'owner_previous':snap.get('owner')})
    return jsonify({'ok':True,'paper':True,'order':{'id':data.get('id'),'status':data.get('status'),'symbol':data.get('symbol'),'qty':data.get('qty')}}),202

@app.post('/api/stonks/paper-position/close-single')
@_stonks_serialized
def stonks_close_single_paper_position_api():
    """Close the only blocking Alpaca Paper position after explicit user confirmation.

    Paper-only recovery action for ownership-transfer deadlocks. It never touches Live,
    requires exactly one open Paper position and zero open Paper orders, and rechecks
    symbol/quantity immediately before submitting the market SELL.
    """
    payload=request.get_json(silent=True) or {}
    if payload.get('confirm') is not True:
        return jsonify({'ok':False,'error':'Hace falta confirmación explícita para cerrar la posición Paper.'}),400
    positions=_alpaca_paper_request('/v2/positions')
    orders=_alpaca_paper_request('/v2/orders', params={'status':'open','limit':500,'nested':'false'})
    if not isinstance(positions,list) or not isinstance(orders,list):
        return jsonify({'ok':False,'error':'No se pudo verificar la exposición Alpaca Paper.'}),502
    if len(positions)!=1:
        return jsonify({'ok':False,'error':f'Esta recuperación exige exactamente 1 posición Paper abierta; ahora hay {len(positions)}.'}),409
    if orders:
        return jsonify({'ok':False,'error':f'Hay {len(orders)} orden(es) Paper abierta(s). Resuélvelas antes de cerrar la posición bloqueante.'}),409
    pos=positions[0]
    symbol=str(pos.get('symbol') or '').upper().strip()
    qty=str(pos.get('qty') or '').strip()
    try:
        if not symbol or float(qty)<=0:
            raise ValueError
    except Exception:
        return jsonify({'ok':False,'error':'La posición Paper no tiene símbolo/cantidad válidos.'}),409
    requested_symbol=str(payload.get('symbol') or symbol).upper().strip()
    requested_qty=str(payload.get('qty') or qty).strip()
    try:
        qty_match=abs(float(requested_qty)-float(qty)) <= max(1e-9, abs(float(qty))*1e-8)
    except Exception:
        qty_match=False
    if requested_symbol!=symbol or not qty_match:
        return jsonify({'ok':False,'error':'La posición cambió desde que se mostró en pantalla. Actualiza la cartera y vuelve a intentarlo.'}),409
    account=_alpaca_paper_request('/v2/account')
    if account.get('status')!='ACTIVE' or account.get('trading_blocked') or account.get('account_blocked'):
        return jsonify({'ok':False,'error':'La cuenta Alpaca Paper no está operativa.'}),409
    cid=('zar-paper-recovery-close-'+uuid.uuid4().hex[:16])[:48]
    body={'symbol':symbol,'qty':qty,'side':'sell','type':'market','time_in_force':'gtc' if _stonks_is_crypto(symbol) else 'day','client_order_id':cid}
    try:
        data=_stonks_submit_paper_order(body)
    except (RuntimeError, requests.RequestException, ValueError):
        return jsonify({'ok':False,'error':'Alpaca Paper no confirmó el cierre de la posición.'}),502
    _stonks_audit_append('PAPER_BLOCKING_POSITION_CLOSE',{'paper':True,'symbol':symbol,'qty':qty,'order_id':data.get('id')})
    return jsonify({'ok':True,'paper':True,'order':{'id':data.get('id'),'status':data.get('status'),'symbol':data.get('symbol'),'qty':data.get('qty')}}),202

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
        if not symbol or len(symbol)>24 or not symbol.replace('.','').replace('-','').replace('/','').isalnum():
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
        clock=_stonks_market_clock_snapshot()
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
        return jsonify({'ok':True,'paper':True,'positions':[_stonks_normalize_broker_row(x) for x in data] if isinstance(data,list) else []})
    except Exception as exc:
        return jsonify({'ok':False,'error':str(exc)}),502

@app.get('/api/stonks/alpaca/position/<path:symbol>')
def stonks_alpaca_position_get_api(symbol):
    symbol=_stonks_symbol_key(symbol)
    if not symbol or len(symbol)>24 or not symbol.replace('.','').replace('-','').replace('/','').isalnum():
        return jsonify({'ok':False,'error':'Símbolo no válido.'}),400
    try:
        data=_alpaca_paper_request('/v2/positions/'+urlquote(symbol, safe=''))
        return jsonify({'ok':True,'paper':True,'position':_stonks_normalize_broker_row(data)})
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
        if d.get('execution_mode') == 'shadow':
            return jsonify({'ok':False,'error':'Shadow no permite enviar órdenes Paper.'}),409
        payload=request.get_json(silent=True) or {}
        symbol=_stonks_symbol_key(payload.get('symbol') or 'AAPL')
        side=str(payload.get('side') or 'buy').strip().lower()
        order_type=str(payload.get('type') or 'limit').strip().lower()
        tif=str(payload.get('time_in_force') or 'day').strip().lower()
        try: qty=float(payload.get('qty'))
        except Exception: qty=0
        try: limit_price=float(payload.get('limit_price')) if payload.get('limit_price') not in (None,'') else None
        except Exception: limit_price=None
        if not symbol or len(symbol)>24 or not symbol.replace('.','').replace('-','').replace('/','').isalnum():
            return jsonify({'ok':False,'error':'Símbolo no válido.'}),400
        if side not in ('buy','sell'):
            return jsonify({'ok':False,'error':'El lado debe ser buy o sell.'}),400
        if order_type not in ('market','limit'):
            return jsonify({'ok':False,'error':'Solo se permiten órdenes market o limit en este primer bloque.'}),400
        if tif not in ('day','gtc','ioc'):
            return jsonify({'ok':False,'error':'Time in force no válido. Usa day, gtc o ioc.'}),400
        import math
        if not math.isfinite(qty) or qty <= 0 or qty > 10000:
            return jsonify({'ok':False,'error':'Cantidad no válida.'}),400
        if order_type == 'limit' and (limit_price is None or not math.isfinite(limit_price) or limit_price <= 0):
            return jsonify({'ok':False,'error':'Una orden limit necesita un precio límite positivo.'}),400
        if order_type == 'market' and ((_stonks_is_crypto(symbol) and tif not in ('gtc','ioc')) or (not _stonks_is_crypto(symbol) and tif != 'day')):
            return jsonify({'ok':False,'error':'Time in force incompatible con el tipo de activo.'}),400

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
                last, _manual_clock = _stonks_latest_price(symbol)
                px=float(stonks_lifecycle.number(last.get('p') or 0))
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
            positions=[_stonks_normalize_broker_row(x) for x in positions]
            current=next((p for p in positions if _stonks_symbol_key(p.get('symbol'))==symbol),None)
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
        data=_stonks_submit_paper_order(body)
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
            previous_claims_control = bool(
                previous.get('autonomous_engine')
                or stonks_lifecycle.active_records(previous)
                or previous.get('pending_entries')
                or any(r.get('status')!='CERRADA' for r in previous.get('managed_positions',{}).values())
            )
            if previous_claims_control:
                # v32.0.3: local ownership can survive a browser/session change even after
                # the real Paper exposure has disappeared.  Alpaca Paper is the source of
                # truth before allowing a takeover.  Fail closed when broker state cannot
                # be verified, and never transfer while any Paper position/order is open.
                try:
                    broker_positions = _alpaca_paper_request('/v2/positions')
                    broker_orders = _alpaca_paper_request('/v2/orders', params={
                        'status':'open','limit':500,'nested':'false'
                    })
                    if not isinstance(broker_positions, list) or not isinstance(broker_orders, list):
                        raise RuntimeError('Estado Paper no verificable')
                except Exception:
                    return jsonify({'ok':False,'error':'No se puede verificar la exposición de Alpaca Paper. El control no se transferirá hasta confirmar posiciones y órdenes abiertas.'}),409
                if broker_positions or broker_orders:
                    return jsonify({'ok':False,'error':f'Otro espacio conserva el control y Alpaca Paper aún tiene exposición activa: {len(broker_positions)} posición(es) y {len(broker_orders)} orden(es) abierta(s). Resuélvela antes de transferir el motor.'}),409
                # No broker exposure remains: the persisted owner is stale.  The global
                # worker follows engine_owner.json every cycle, so moving ownership here
                # cannot create a second engine.  Preserve historical records; only clear
                # stale execution claims in the old scope.
                previous['autonomous_engine']=False
                previous['pending_entries']={}
                previous['engine_last_action']='Owner huérfano liberado tras verificar 0 exposición en Alpaca Paper.'
                with app.test_request_context('/api/stonks/engine/owner-release'):
                    session['zar_user_id']=owner
                    _stonks_write(previous)
                _stonks_audit_append('OWNER PAPER',{'decision':'LIBERADO','previous_owner':owner,'new_owner':me,'broker_positions':0,'broker_open_orders':0})
        symbols=[]
        for raw in str(payload.get('symbols') or ','.join(d.get('engine_symbols') or ['AAPL'])).split(','):
            sym=_stonks_symbol_key(raw)
            if sym and sym not in symbols: symbols.append(sym)
        if not symbols: symbols=['AAPL']
        if len(symbols)>8: return jsonify({'ok':False,'error':'Máximo 8 símbolos para el motor autónomo.'}),400
        for sym in symbols:
            if len(sym)>24 or not sym.replace('.','').replace('-','').replace('/','').isalnum():
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
        d['engine_auto_universe']=bool(payload.get('auto_universe', d.get('engine_auto_universe', True)))
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

@app.post('/api/stonks/automaton')
@_stonks_serialized
def stonks_automaton_api():
    payload=request.get_json(silent=True) or {}
    action=str(payload.get('action') or '').strip().lower()
    if action not in ('start','pause','stop','kill'):
        return jsonify({'ok':False,'error':'Acción Automaton no válida.'}),400
    d=_stonks_read()
    if action=='start':
        if d.get('mode')!='paper':
            return jsonify({'ok':False,'error':'Automaton solo puede funcionar en modo Paper.'}),409
        if d.get('revoked'):
            return jsonify({'ok':False,'error':'El kill switch está revocado. Restaura primero el control de ZAR Stonks.'}),409
        # Automaton is an orchestrator over the existing Paper engine, never a new order path.
        requested_mode=str(payload.get('automaton_mode') or 'PAPER').upper()
        if requested_mode not in ('SHADOW','PAPER'):
            return jsonify({'ok':False,'error':'LIVE desconectado; selecciona SHADOW o PAPER.'}),409
        d['execution_mode']='shadow' if requested_mode=='SHADOW' else 'paper_auto'
        d['autonomous_engine']=True
        d['paused']=False
        stonks_automaton.start(d)
        _stonks_write(d)
        _stonks_engine_owner_write(_user_scope_id())
        _stonks_audit_append('AUTOMATON',{'decision':'ENCENDIDO','paper_only':True,'execution_mode':d['execution_mode']})
    elif action=='pause':
        d['paused']=True
        stonks_automaton.pause(d)
        _stonks_write(d)
        _stonks_audit_append('AUTOMATON',{'decision':'PAUSADO','paper_only':True})
    else:
        if action=='kill':
            d['paused']=True;d['revoked']=True;d['mode']='paper'
        stonks_automaton.stop(d)
        d['autonomous_engine']=False
        _stonks_write(d)
        _stonks_audit_append('AUTOMATON',{'decision':'KILL_SWITCH' if action=='kill' else 'APAGADO','paper_only':True})
    return jsonify({'ok':True,'automaton':stonks_automaton.public_view(d),
                    'autonomous_engine':bool(d.get('autonomous_engine')),
                    'execution_mode':d.get('execution_mode'),'paused':bool(d.get('paused')),
                    'revoked':bool(d.get('revoked'))})

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
    result = {"ok": True, **smart_catalog(load())}
    from . import node_inference
    if node_inference.enabled():
        result["gateway"] = node_inference.status()
    return jsonify(result)

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
        return jsonify({"ok": True, "contacts": sorted(search_contacts(q, 500), key=lambda c: (c.get("name") or "").casefold())})
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
        from . import node_inference
        if node_inference.enabled():
            status = node_inference.status()
            return jsonify({"ok":status["state"]=="ONLINE" or status.get("provider")=="local", "reply":reply, **status})
        return jsonify({"ok":True,"reply":reply})
    except Exception as exc:
        return jsonify({"ok":False,"reply":str(exc)})

def _set_pending_workspace_action(pending):
    """Persist a Workspace action in both durable user context and browser session.

    The session copy survives user-scope migrations/rebinding during Google flows,
    while the context copy remains the canonical persistent state.
    """
    set_pending_workspace(pending)
    try:
        session['zar_pending_workspace']=pending
        session.modified=True
    except Exception:
        pass
    return pending


def _clear_pending_workspace_action():
    clear_pending_workspace()
    try:
        session.pop('zar_pending_workspace', None)
        session.modified=True
    except Exception:
        pass


def _workspace_pending_from_marker(reply):
    """Persist a structured WORKSPACE_ACTION marker and return the pending payload.

    This is the canonical bridge between model tool-calling and the explicit
    confirmation layer. It never executes the external action.
    """
    if not (isinstance(reply, str) and reply.startswith("WORKSPACE_ACTION::")):
        return None
    try:
        data = json.loads(reply.split("::", 1)[1])
        pending = {
            "service": data.get("service", "Google Workspace"),
            "action": data.get("action", "realizar una acción"),
            "args": data.get("args") or {},
        }
        if not pending["args"]:
            return None
        _set_pending_workspace_action(pending)
        set_task_state(
            "google workspace",
            (pending.get("service") or "workspace").lower(),
            "",
            pending.get("action", ""),
            "high",
            "awaiting_confirmation",
            f"Preparado para {pending.get('action','acción')} en {pending.get('service','Google Workspace')}",
        )
        return pending
    except Exception:
        return None


def _workspace_prepare_bridge(original_message):
    """Force a textual Workspace plan to become a real pending action.

    Models can occasionally answer with a polished plan and a confirmation
    question without actually calling the write tool. That looks correct in the
    UI but leaves nothing to execute on the next "sí". This bridge performs a
    hidden, tool-only semantic pass and accepts only a WORKSPACE_ACTION marker.
    """
    text = (original_message or "").strip()
    if not text:
        return None
    try:
        from .agent import semantic_respond
    except ImportError:
        from agent import semantic_respond
    internal = (
        text
        + "\n\n[INSTRUCCIÓN INTERNA DE ZAR — NO RESPONDAS CON UN PLAN EN TEXTO. "
          "Debes PREPARAR AHORA la acción de Google Workspace usando la herramienta de escritura adecuada. "
          "Si es una reorganización de un Google Sheets existente, localiza el archivo real si hace falta y usa "
          "sheets_upgrade_workbook. No ejecutes la modificación todavía: la herramienta debe devolver el marcador "
          "WORKSPACE_ACTION para que la aplicación solicite una única confirmación. No preguntes nada al usuario.]"
    )
    try:
        marker = semantic_respond(internal)
    except Exception:
        return None
    return _workspace_pending_from_marker(marker)


def _looks_like_workspace_request(text):
    return bool(re.search(
        r"\b(workspace|google\s+(?:sheets|docs|slides|forms|drive)|sheets|hoja de c[aá]lculo|excel|docs?|documento|slides|presentaci[oó]n|formulario)\b",
        text or "", re.I
    ))


def _looks_like_workspace_write_request(text):
    if not _looks_like_workspace_request(text):
        return False
    return bool(re.search(
        r"\b(crea(?:r|me)?|crear|haz|hacer|modifica(?:r)?|editar?|reorganiza(?:r)?|actualiza(?:r)?|"
        r"añade|agrega|inserta|escribe|formatea|mejora|convierte|prepara|genera|diseña|ordena)\b",
        text or "", re.I
    ))


def _workspace_requires_analysis_first(text):
    """True when the user explicitly wants evidence/file analysis before any Workspace write.

    This prevents the confirmation bridge from preparing a Sheets mutation merely
    because the same message mentions a later write step. The analysis/extraction
    phase must finish and be shown to the user first.
    """
    t=(text or "").lower()
    if not _looks_like_workspace_request(t):
        return False
    has_analysis=bool(re.search(r"\b(analiza|analizar|extrae|extraer|lee|leer|revisa|revisar|datos\s+extra[ií]dos|archivo\s+adjunt|foto\s+adjunt|ticket|evidencia)\b", t, re.I))
    before_write=bool(re.search(r"(?:antes\s+de|primero|previamente).{0,120}(?:modificar|actualizar|escribir|guardar|google\s+sheets|hoja\s+de\s+c[aá]lculo)", t, re.I|re.S))
    show_first=bool(re.search(r"(?:mu[eé]strame|dime|ens[eé][nñ]ame|resume).{0,100}(?:datos|extra[ií]do|an[aá]lisis|resultado)", t, re.I|re.S))
    return has_analysis and (before_write or show_first)


def _looks_like_confirmation_plan(reply):
    if not isinstance(reply, str):
        return False
    # Accept natural variants the model may use when asking permission.
    # Do not depend on one exact phrase such as “¿Confirmas?”.
    return bool(re.search(
        r"\b(confirm(?:as|a|o|amos|aci[oó]n)?|autoriz(?:as|a|o|aci[oó]n)?|procedo|procedemos|"
        r"responde(?:\s+simplemente)?\s+[«\"']?s[ií]|puedo\s+proceder|me\s+das\s+permiso|"
        r"quieres\s+(?:que\s+)?(?:lo\s+)?(?:registre|registrar|guarde|guardar|cree|crear|modifique|modificar|env[ií]e|enviar|a[nñ]ada|añadir|proceda|continuar))\b",
        reply, re.I
    ))


def _last_assistant_workspace_confirmation():
    """Return True when the most recent assistant turn is a Workspace confirmation.

    This intentionally relies on conversation evidence rather than volatile task
    state so an explicit “Sí” can recover after a partial persistence failure.
    """
    try:
        items = conversation()[-12:] or history()[-12:]
    except Exception:
        items = []
    for item in reversed(items):
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if not content:
            continue
        if role == "assistant":
            # The assistant may say only “¿Confirmo y procedo con la hoja?”
            # without repeating “Google Sheets”. Confirmation evidence alone is
            # enough here; the recovered user turn is separately required to be
            # a genuine Workspace request before any action is reconstructed.
            return _looks_like_confirmation_plan(content)
        if role == "user":
            # Stop at a substantive new user turn. A bare confirmation is allowed
            # because this helper is evaluated while processing that same turn.
            if not _looks_like_send(content):
                return False
    return False


def _last_workspace_request_from_history():
    """Recover the latest substantive Workspace request for confirmation repair."""
    try:
        items = conversation()[-30:] or history()[-30:]
    except Exception:
        items = []
    for item in reversed(items):
        if item.get("role") != "user":
            continue
        content = (item.get("content") or "").strip()
        if not content or _looks_like_send(content) or _looks_like_cancel(content):
            continue
        if _looks_like_workspace_request(content):
            return content
    return ""



def _clean_model_ui_markup(text):
    """Remove model-authored action HTML. Interactive controls belong to the trusted UI only."""
    if not isinstance(text, str):
        return text
    out=text
    # Remove blocks that contain model-authored buttons/scripts, including escaped-looking raw HTML.
    out=re.sub(r'(?is)<div\b[^>]*>\s*(?:(?!</div>).)*?<button\b.*?</div>', '', out)
    out=re.sub(r'(?is)<button\b[^>]*>.*?</button>', '', out)
    out=re.sub(r'(?is)<script\b[^>]*>.*?</script>', '', out)
    out=re.sub(r'(?im)^\s*</?div[^>]*>\s*$', '', out)
    out=re.sub(r'\n{3,}', '\n\n', out).strip()
    return out


def _prepare_business_sync_pending(original_message, assistant_reply=''):
    """Prepare Room/business evidence sync deterministically after an analyze-first turn.

    This closes the unsafe gap where the model could ask '¿Quieres registrar estos datos?'
    without having created a structured Workspace action.
    """
    text=((original_message or '')+'\n'+(assistant_reply or '')).lower()
    if not re.search(r'\b(cierre|caja|room\s*108|control de cierres|evidencia)\b', text, re.I):
        return None
    if not _looks_like_confirmation_plan(assistant_reply):
        return None
    last=get_context().get('last_uploaded_file') or {}
    file_id=last.get('id') if isinstance(last,dict) else None
    if not file_id:
        return None
    # Prefer an explicit quoted spreadsheet name; otherwise use the established Room108 book.
    name='Control de Cierres y Horas - Room108'
    m=re.search(r'[«\"]([^»\"]*(?:cierres|room\s*108)[^»\"]*)[»\"]', original_message or '', re.I)
    if m and m.group(1).strip():
        name=m.group(1).strip()
    try:
        from . import google_workspace as gw
    except ImportError:
        import google_workspace as gw
    try:
        found=gw.drive_search(name,20)
    except Exception:
        found=[]
    sheet=next((x for x in found if x.get('mimeType')=='application/vnd.google-apps.spreadsheet'),None)
    if not sheet:
        # More tolerant lookup for punctuation/name variants.
        try:
            found=gw.drive_search('Room108',30)+gw.drive_search('Room 108',30)
            sheet=next((x for x in found if x.get('mimeType')=='application/vnd.google-apps.spreadsheet'),None)
        except Exception:
            sheet=None
    if sheet:
        pending={'service':'Google Sheets','action':'sincronizar control de negocio','args':{
            'spreadsheet_id':sheet.get('id'),'business_name':'Room 108','file_ids':[str(file_id)]
        }}
        task_target=sheet.get('id','')
        task_summary=f'Preparado para registrar evidencia en {sheet.get("name") or name}'
    else:
        # Confirmation must not depend on a pre-confirmation Drive lookup.  Keep a
        # deterministic deferred action containing the evidence and intended book;
        # the exact spreadsheet is resolved only after the user presses Confirmar.
        pending={'service':'Google Sheets','action':'sincronizar control de negocio diferido','args':{
            'spreadsheet_name':name,'business_name':'Room 108','file_ids':[str(file_id)]
        }}
        task_target=name
        task_summary=f'Preparado para localizar {name} y registrar la evidencia al confirmar'
    _set_pending_workspace_action(pending)
    set_task_state('google workspace','google sheets',task_target,pending.get('action','sincronizar control de negocio'),'high','awaiting_confirmation',task_summary)
    return pending

def _execute_workspace_action(pending):
    service = pending.get("service")
    action = pending.get("action")
    args = pending.get("args") or {}
    try:
        from . import google_workspace as gw
    except ImportError:
        import google_workspace as gw
    if service == "Google Docs":
        if action == "crear documento": return gw.docs_create(args["title"], args.get("text", ""))
        if action == "crear informe profesional": return gw.docs_build_report(args["title"], args.get("subtitle", ""), args.get("sections") or [])
        return gw.docs_append(args["document_id"], args["text"])
    if service == "Google Sheets":
        if action == "crear hoja de cálculo": return gw.sheets_create(args["title"])
        if action == "crear libro profesional": return gw.sheets_build_workbook(args["title"], args.get("sheets") or [])
        if action == "reorganizar libro profesional": return gw.sheets_upgrade_workbook(args["spreadsheet_id"], args.get("tabs") or [], args.get("charts") or [])
        if action == "sincronizar control de negocio": return gw.sheets_sync_business_control(args["spreadsheet_id"], args.get("file_ids") or [], args.get("business_name") or "Room 108")
        if action == "sincronizar control de negocio diferido":
            wanted=(args.get("spreadsheet_name") or "Control de Cierres y Horas - Room108").strip()
            candidates=[]
            for query in (wanted, "Room108", "Room 108"):
                try:
                    candidates.extend(gw.drive_search(query,30) or [])
                except Exception:
                    continue
            sheets=[x for x in candidates if x.get('mimeType')=='application/vnd.google-apps.spreadsheet']
            if not sheets:
                raise RuntimeError(f'No encuentro la hoja de Google Sheets «{wanted}». No se ha modificado ningún archivo.')
            def _norm(v):
                return re.sub(r'[^a-z0-9]+','',str(v or '').lower())
            exact=next((x for x in sheets if _norm(x.get('name'))==_norm(wanted)),None)
            chosen=exact or sheets[0]
            return gw.sheets_sync_business_control(chosen["id"], args.get("file_ids") or [], args.get("business_name") or "Room 108")
        if action == "modificar estilo visual": return gw.sheets_style_range(args["spreadsheet_id"], args["sheet_title"], args["range_a1"], args.get("style") or {})
        if action == "añadir tabla profesional": return gw.sheets_add_professional_table(args["spreadsheet_id"], args["sheet_title"], args["table_title"], args.get("headers") or [], args.get("rows") or [], args.get("start_cell") or "A1", args.get("subtitle") or "", args.get("summary") or [])
        return gw.sheets_write(args["spreadsheet_id"], args["range_a1"], args["values"])
    if service == "Google Slides":
        if action == "crear presentación profesional": return gw.slides_build_deck(args["title"], args.get("subtitle", ""), args.get("slides") or [])
        return gw.slides_create(args["title"])
    if service == "Google Forms":
        if action == "crear formulario":
            return gw.forms_create(args["title"], args.get("description", ""))
        if action == "añadir pregunta":
            return gw.forms_add_question(args["form_id"], args["question"], args.get("required", False), args.get("paragraph", False))
    raise RuntimeError("Acción de Google Workspace no reconocida.")


def _process_chat_message(msg):
    low = (msg or "").strip().lower()
    # UI confirmation buttons use explicit internal decisions. They are mapped
    # here, before any intent routing, so confirmation never depends on NLU.
    if low == "__zar_confirm__":
        msg = "sí"
        low = "sí"
    elif low == "__zar_cancel__":
        msg = "cancelar"
        low = "cancelar"
    ctx = _ctx()
    pending_email = ctx.get("pending_email")
    LAST_EMAIL = ctx.get("active_email")
    pending_contact = ctx.get("pending_contact")
    pending_calendar = ctx.get("pending_calendar")
    if pending_calendar and pending_calendar.get("event") and _looks_like_send(msg):
        try:
            event = pending_calendar.get("event") or {}
            result = execute_tool("calendar_create_confirmed", event)
            clear_pending_calendar()
            clear_task_state()
            reply = "✅ He creado el evento en Google Calendar."
            if isinstance(result, dict) and result.get("htmlLink"):
                reply += "\n" + result.get("htmlLink")
        except Exception as exc:
            reply = f"No he podido crear el evento en Google Calendar: {exc}"
        _remember_turn("user", msg); _remember_turn("assistant", reply); return reply
    if pending_calendar and _looks_like_cancel(msg):
        clear_pending_calendar(); clear_task_state()
        reply = "✅ He cancelado la creación del evento de Google Calendar."
        _remember_turn("user", msg); _remember_turn("assistant", reply); return reply
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
    pending_workspace = ctx.get("pending_workspace") or session.get("zar_pending_workspace")

    if pending_workspace and _looks_like_send(msg):
        try:
            result = _execute_workspace_action(pending_workspace)
            _clear_pending_workspace_action()
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
        _clear_pending_workspace_action()
        reply = "✅ He cancelado la acción pendiente de Google Workspace."
        _remember_turn("user",msg); _remember_turn("assistant",reply)
        return reply


    if _looks_like_send(msg):
        task=(ctx.get("task") or {})
        workspace_confirmation_evidence = (
            task.get("status")=="awaiting_confirmation" and task.get("intent")=="google workspace"
        ) or _last_assistant_workspace_confirmation()
        if workspace_confirmation_evidence and not pending_workspace:
            # Recovery path: if persistence was partial, reconstruct the latest
            # Workspace request from history. The explicit user “Sí” is the
            # authorization; never ask them to repeat the request.
            original = _last_workspace_request_from_history()
            recovered = _workspace_prepare_bridge(original) if original else None
            if recovered:
                try:
                    result = _execute_workspace_action(recovered)
                    _clear_pending_workspace_action()
                    try:
                        from .context import set_last_workspace
                    except ImportError:
                        from context import set_last_workspace
                    workspace_obj = dict(result or {})
                    workspace_obj.update({"service": recovered.get("service"), "action": recovered.get("action"), "requested_args": recovered.get("args") or {}})
                    set_last_workspace(workspace_obj)
                    set_task_state("google workspace", (recovered.get("service") or "workspace").lower(), result.get("id", result.get("documentId", result.get("spreadsheetId", result.get("presentationId", result.get("formId", ""))))), recovered.get("action", ""), "high", "completed", f"Acción realizada en {recovered.get('service')}")
                    url = result.get("url") or result.get("htmlLink") or ""
                    reply = f"✅ He realizado la acción en {recovered.get('service')}." + (f"\n{url}" if url else "")
                except Exception as exc:
                    reply = f"No he podido realizar la acción recuperada de Google Workspace: {exc}"
                _remember_turn("user",msg); _remember_turn("assistant",reply); return reply
            reply=("La confirmación de Workspace existe, pero no he podido reconstruir de forma segura la acción pendiente. "
                   "No he modificado ningún archivo. Repite la orden completa y ZAR la preparará de nuevo antes de pedir confirmación.")
            _remember_turn("user",msg); _remember_turn("assistant",reply); return reply

    if _looks_like_cancel(msg) and _last_assistant_workspace_confirmation():
        # A natural-language confirmation may exist even if the model failed to
        # persist a structured payload. Cancellation is always safe: clear any
        # partial confirmation state and do not execute anything.
        _clear_pending_workspace_action()
        clear_task_state()
        reply = "✅ Acción cancelada. No he modificado ningún archivo ni servicio externo."
        _remember_turn("user", msg); _remember_turn("assistant", reply); return reply

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
                _set_pending_workspace_action(pending)
                set_task_state("google workspace", (pending.get("service") or "workspace").lower(), "", pending.get("action", ""), "high", "awaiting_confirmation", f"Preparado para {pending.get('action','acción')} en {pending.get('service','Google Workspace')}")
                reply = f"⚠️ La habilidad «{used_skill.get('name')}» ha preparado la acción: {pending.get('action','acción')} en {pending.get('service','Google Workspace')}.\n\nUsa los botones Confirmar o Cancelar."
            elif isinstance(reply, str) and reply.startswith("CONTACT_ACTION::"):
                data = json.loads(reply.split("::", 1)[1])
                pending = {"action": data.get("action"), "args": data.get("args") or {}}
                from .context import set_pending_contact
                set_pending_contact(pending)
                set_task_state("google contacts", "contact", "", pending.get("action", ""), "high", "awaiting_confirmation", f"Preparado para {pending.get('action','acción')}")
                reply = f"⚠️ La habilidad «{used_skill.get('name')}» ha preparado una acción de Google Contacts.\n\nUsa los botones Confirmar o Cancelar."
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
                reply = _clean_model_ui_markup(semantic_reply)
                if isinstance(reply, str) and reply.startswith("HE_EMAIL::"):
                    import json as _json
                    draft = _json.loads(reply.split("::",1)[1])
                    _set_pending(_pending_email_from(draft)); set_focus("email_draft", draft.get("subject") or "borrador actual")
                    reply = _email_card(draft, question=True)
                elif isinstance(reply, str) and reply.startswith("WORKSPACE_ACTION::"):
                    # El agente semántico ha elegido una acción de Google Workspace.
                    # Nunca mostramos el marcador interno al usuario: convertimos la
                    # acción en una operación pendiente y pedimos confirmación explícita.
                    pending = _workspace_pending_from_marker(reply)
                    if pending:
                        reply = (
                            f"⚠️ Voy a {pending.get('action','realizar esta acción')} en "
                            f"{pending.get('service','Google Workspace')}.\n\n"
                            "Usa los botones Confirmar o Cancelar para continuar."
                        )
                elif _looks_like_workspace_write_request(msg) and not _workspace_requires_analysis_first(msg):
                    # Deterministic Workspace bridge: whenever a Workspace write
                    # request returns prose instead of WORKSPACE_ACTION, attempt to
                    # create the structured pending action before returning to the
                    # user. This no longer depends on the exact wording of the
                    # model's confirmation question (e.g. “¿Confirmo y procedo?”).
                    pending = _workspace_prepare_bridge(msg)
                    if pending:
                        reply = (
                            f"⚠️ He preparado la acción real: {pending.get('action','realizar esta acción')} en "
                            f"{pending.get('service','Google Workspace')}.\n\n"
                            "Usa los botones Confirmar o Cancelar para continuar."
                        )
                    elif _looks_like_confirmation_plan(reply):
                        reply = (
                            "No he podido preparar de forma segura la acción de Google Workspace todavía. "
                            "No he modificado ningún archivo. Inténtalo de nuevo y ZAR preparará la acción antes de pedir confirmación."
                        )
                elif _workspace_requires_analysis_first(msg) and _looks_like_confirmation_plan(reply):
                    pending = _prepare_business_sync_pending(msg, reply)
                    if pending:
                        reply = _clean_model_ui_markup(reply)
                    else:
                        reply = _clean_model_ui_markup(reply)
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
                    "sheets_add_professional_table": ("Google Sheets", "añadir tabla profesional"),
                    "sheets_build_workbook": ("Google Sheets", "crear libro profesional"),
                    "sheets_upgrade_workbook": ("Google Sheets", "reorganizar libro profesional"),
                    "sheets_sync_business_control": ("Google Sheets", "sincronizar control de negocio"),
                    "sheets_style_range": ("Google Sheets", "modificar estilo visual"),
                    "slides_create": ("Google Slides", "crear presentación"),
                    "slides_build_deck": ("Google Slides", "crear presentación profesional"),
                    "docs_build_report": ("Google Docs", "crear informe profesional"),
                    "forms_create": ("Google Forms", "crear formulario"),
                }
                if typ in mapping:
                    service, action = mapping[typ]
                    args = dict(data)
                    args.pop("type", None)
                    pending = {"service": service, "action": action, "args": args}
                    _set_pending_workspace_action(pending)
                    set_task_state("google workspace", service.lower(), "", action, "high", "awaiting_confirmation", f"Preparado para {action} en {service}")
                    reply = f"⚠️ Voy a {action} en {service}.\n\nUsa los botones Confirmar o Cancelar para continuar."
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
                    "\nUsa los botones Confirmar o Cancelar para continuar."
                )
            except Exception as exc:
                reply = f"No he podido preparar la acción de Google Contacts: {exc}"
        if isinstance(reply, str) and reply.startswith("WORKSPACE_ACTION::"):
            try:
                data = json.loads(reply.split("::", 1)[1])
                pending = {k: data.get(k) for k in ("service", "action", "args")}
                _set_pending_workspace_action(pending)
                set_task_state("google workspace", (data.get("service") or "workspace").lower(), "", data.get("action", ""), "high", "awaiting_confirmation", f"Preparado para {data.get('action','acción')} en {data.get('service','Google Workspace')}")
                reply = f"⚠️ Voy a {data.get('action','realizar esta acción')} en {data.get('service','Google Workspace')}.\n\nUsa los botones Confirmar o Cancelar para continuar."
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
    # Snapshot only serialisable session state needed by background chat execution.
    # The worker restores it inside its own isolated Flask request context.
    try:
        session_snapshot = dict(session)
    except Exception:
        session_snapshot = {}
    _write_job(job_id, "running", user_id=user_id)
    threading.Thread(target=_run_chat_job, args=(job_id, msg, user_id, session_snapshot), daemon=True).start()
    return jsonify({"job_id": job_id, "status": "running"}), 202

@app.get("/api/jobs/<job_id>")
def job_status(job_id):
    job = _read_job(job_id)
    if not job:
        return jsonify({"status":"not_found"}), 404
    if job.get("user_id") and job.get("user_id") != get_current_user():
        return jsonify({"status":"not_found"}), 404
    return jsonify(job)

@app.get("/api/confirmation-status")
def confirmation_status():
    """Return the current structured confirmation for the active user.

    Background chat workers can persist the action after the job response object has
    already been assembled.  This endpoint gives the browser a durable source of
    truth so confirmation controls never depend on one transient job payload.
    """
    ctx = _ctx()
    pending_workspace = ctx.get("pending_workspace") or session.get("zar_pending_workspace")
    if pending_workspace:
        return jsonify({
            "required": True,
            "kind": "workspace",
            "title": pending_workspace.get("service") or "Google Workspace",
            "action": pending_workspace.get("action") or "acción pendiente",
        })
    pending_contact = ctx.get("pending_contact")
    if pending_contact:
        return jsonify({
            "required": True,
            "kind": "contact",
            "title": "Google Contacts",
            "action": pending_contact.get("action") or "modificar contacto",
        })
    if ctx.get("pending_email"):
        return jsonify({"required": True, "kind": "email", "title": "Gmail", "action": "enviar correo"})
    if (ctx.get("pending_calendar") or {}).get("event"):
        return jsonify({"required": True, "kind": "calendar", "title": "Google Calendar", "action": "crear evento"})
    return jsonify({"required": False})

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
        result = voice_pro.transcribe(f.stream, f.mimetype or "audio/webm", f.filename or "voz.webm")
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
        audio, mime, voice_provider = voice_pro.synthesize(text, voice=voice, language=language)
        return jsonify({"ok": True, "mime": mime, "audio_base64": base64.b64encode(audio).decode("ascii"), "provider": voice_provider})
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
            _set_pending_workspace_action(pending)
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

def _holdings_engine_loop():
    while True:
        try:
            if _stonks_process_owns_engine():
                for _scope in holdings.active_scope_ids():
                    company_runtime.cycle_scope(_scope)
        except Exception:
            pass
        time.sleep(max(5, int(os.environ.get('ZAR_HOLDINGS_CYCLE_SECONDS','10'))))

_holdings_engine_thread=threading.Thread(target=_holdings_engine_loop, name='zar-holdings-runtime', daemon=True)
_holdings_engine_thread.start()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT','8765')), debug=False)
