"""Persistent, read-only Google account snapshots for Zar.

The snapshot is intentionally independent from Google's live connection: after
one successful authorization, Zar can search the local copy of Gmail,
Contacts, Calendar, Tasks and Drive even when Google is temporarily offline or
the user revokes the connection. The raw snapshot remains under ZAR_DATA_DIR.
"""
import base64
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from io import BytesIO

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from .cloud_auth import get_credentials
from .user_scope import safe_slug, get_current_user, set_current_user

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("ZAR_DATA_DIR", str(ROOT / "data")))
BACKUP_ROOT = DATA_DIR / "backups" / "google"
BACKUP_ROOT.mkdir(parents=True, exist_ok=True)

def _backup_root(user_id=None):
    d = BACKUP_ROOT / safe_slug(user_id or get_current_user())
    d.mkdir(parents=True, exist_ok=True)
    return d
_LOCK = threading.Lock()
_LAST = {"status": "never", "started_at": None, "finished_at": None, "path": None, "error": None, "progress": 0, "current_service": None, "completed_services": 0, "total_services": 5, "message": "Sin copia en curso.", "service_states": {}}

DEFAULT_BACKUP_OPTIONS = {
    "gmail": {"messages": True, "drafts": True, "attachments": True},
    "contacts": True,
    "calendar": True,
    "tasks": True,
    "drive": {"metadata": True, "content": True},
}

def normalize_backup_options(options=None):
    """Normalize the user's backup selection; defaults to a complete Google snapshot."""
    if not isinstance(options, dict):
        options = {}
    out = {
        "gmail": {
            "messages": bool((options.get("gmail") or {}).get("messages", DEFAULT_BACKUP_OPTIONS["gmail"]["messages"])),
            "drafts": bool((options.get("gmail") or {}).get("drafts", DEFAULT_BACKUP_OPTIONS["gmail"]["drafts"])),
            "attachments": bool((options.get("gmail") or {}).get("attachments", DEFAULT_BACKUP_OPTIONS["gmail"]["attachments"])),
        },
        "contacts": bool(options.get("contacts", DEFAULT_BACKUP_OPTIONS["contacts"])),
        "calendar": bool(options.get("calendar", DEFAULT_BACKUP_OPTIONS["calendar"])),
        "tasks": bool(options.get("tasks", DEFAULT_BACKUP_OPTIONS["tasks"])),
        "drive": {
            "metadata": bool((options.get("drive") or {}).get("metadata", DEFAULT_BACKUP_OPTIONS["drive"]["metadata"])),
            "content": bool((options.get("drive") or {}).get("content", DEFAULT_BACKUP_OPTIONS["drive"]["content"])),
        },
    }
    # Attachments need message traversal to know which message owns them.
    if out["gmail"]["attachments"]:
        out["gmail"]["messages"] = True
    if not (out["gmail"]["messages"] or out["gmail"]["drafts"] or out["gmail"]["attachments"]):
        out["gmail"] = {"messages": False, "drafts": False, "attachments": False}
    return out

def _has_backup_selection(options):
    o = normalize_backup_options(options)
    return any([o["gmail"]["messages"], o["gmail"]["drafts"], o["gmail"]["attachments"], o["contacts"], o["calendar"], o["tasks"], o["drive"]["metadata"], o["drive"]["content"]])


def _json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _safe_name(name, fallback="file"):
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name or "")).strip("._")
    return (name[:120] or fallback)


def _services(creds):
    return {
        "gmail": build("gmail", "v1", credentials=creds, cache_discovery=False),
        "people": build("people", "v1", credentials=creds, cache_discovery=False),
        "calendar": build("calendar", "v3", credentials=creds, cache_discovery=False),
        "drive": build("drive", "v3", credentials=creds, cache_discovery=False),
        "tasks": build("tasks", "v1", credentials=creds, cache_discovery=False),
    }


def _decode_gmail_part(part):
    body = (part or {}).get("body", {}) or {}
    data = body.get("data")
    if not data:
        return ""
    try:
        raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _walk_parts(payload):
    yield payload or {}
    for part in (payload or {}).get("parts", []) or []:
        yield from _walk_parts(part)


def _message_text(msg):
    chunks = []
    for part in _walk_parts(msg.get("payload", {})):
        mime = part.get("mimeType", "")
        if mime in ("text/plain", "text/html"):
            text = _decode_gmail_part(part)
            if text:
                chunks.append(text)
    return "\n".join(chunks).strip()


def _header(msg, name):
    wanted = name.lower()
    for h in (msg.get("payload", {}).get("headers", []) or []):
        if str(h.get("name", "")).lower() == wanted:
            return h.get("value", "")
    return ""


def _backup_gmail(svc, out, options=None, progress_cb=None):
    options = normalize_backup_options(options)["gmail"]
    items = []
    attachment_dir = out / "gmail_attachments"
    attachments_downloaded = 0
    attachments_skipped = 0
    if options["messages"]:
        refs = []
        token = None
        while True:
            data = svc.users().messages().list(userId="me", maxResults=500, includeSpamTrash=True, pageToken=token).execute()
            refs.extend(data.get("messages", []))
            token = data.get("nextPageToken")
            if not token:
                break
        total = max(1, len(refs))
        for pos, ref in enumerate(refs, 1):
            msg = svc.users().messages().get(userId="me", id=ref["id"], format="full").execute()
            items.append(msg)
            if options["attachments"]:
                attachment_dir.mkdir(exist_ok=True)
                for part in _walk_parts(msg.get("payload", {})):
                    filename = part.get("filename")
                    attachment_id = (part.get("body") or {}).get("attachmentId")
                    if not filename or not attachment_id:
                        continue
                    size = int((part.get("body") or {}).get("size") or 0)
                    max_attachment_bytes = int(float(os.environ.get("ZAR_GOOGLE_BACKUP_MAX_ATTACHMENT_MB", "25")) * 1024 * 1024)
                    if size > max_attachment_bytes:
                        attachments_skipped += 1
                        continue
                    try:
                        att = svc.users().messages().attachments().get(userId="me", messageId=msg["id"], id=attachment_id).execute()
                        data64 = att.get("data", "")
                        raw = base64.urlsafe_b64decode(data64 + "=" * (-len(data64) % 4))
                        target = attachment_dir / f"{_safe_name(msg['id'])}_{_safe_name(filename)}"
                        target.write_bytes(raw)
                        attachments_downloaded += 1
                    except Exception:
                        attachments_skipped += 1
            if progress_cb:
                progress_cb(pos / total, f"Gmail · mensaje {pos}/{len(refs)}")
    if options["messages"]:
        _json(out / "messages.json", items)
        _json(out / "labels.json", svc.users().labels().list(userId="me").execute().get("labels", []))
        try:
            profile = svc.users().getProfile(userId="me").execute()
            _json(out / "profile.json", profile)
        except Exception:
            pass
    if options["drafts"]:
        drafts = []
        token = None
        while True:
            data = svc.users().drafts().list(userId="me", maxResults=100, pageToken=token).execute()
            for ref in data.get("drafts", []):
                drafts.append(svc.users().drafts().get(userId="me", id=ref["id"], format="full").execute())
            token = data.get("nextPageToken")
            if not token:
                break
        _json(out / "drafts.json", drafts)
    return {"messages": len(items), "gmail_labels": len(json.loads((out / "labels.json").read_text())) if (out / "labels.json").exists() else 0, "drafts": len(drafts) if options["drafts"] else 0, "gmail_attachments_downloaded": attachments_downloaded, "gmail_attachments_skipped": attachments_skipped}

def _backup_contacts(svc, out, options=None, progress_cb=None):
    people = []
    token = None
    while True:
        data = svc.people().connections().list(
            resourceName="people/me", pageSize=500,
            personFields="names,emailAddresses,phoneNumbers,organizations,photos,metadata,birthdays,addresses,urls,relations",
            pageToken=token,
        ).execute()
        people.extend(data.get("connections", []))
        token = data.get("nextPageToken")
        if not token:
            break
    _json(out / "contacts.json", people)
    if progress_cb: progress_cb(1.0, f"Contactos · {len(people)} contactos")
    return {"contacts": len(people)}


def _backup_calendar(svc, out, options=None, progress_cb=None):
    calendars = svc.calendarList().list(maxResults=250).execute().get("items", [])
    result = []
    for cal in calendars:
        cid = cal.get("id")
        events = []
        token = None
        while True:
            data = svc.events().list(
                calendarId=cid, maxResults=2500, singleEvents=True,
                showDeleted=True, pageToken=token,
            ).execute()
            events.extend(data.get("items", []))
            token = data.get("nextPageToken")
            if not token:
                break
        result.append({"calendar": cal, "events": events})
    _json(out / "calendar.json", result)
    if progress_cb: progress_cb(1.0, f"Calendar · {sum(len(x["events"]) for x in result)} eventos")
    return {"calendars": len(calendars), "events": sum(len(x["events"]) for x in result)}


def _backup_tasks(svc, out, options=None, progress_cb=None):
    result = []
    lists = svc.tasks().tasklists().list(maxResults=100).execute().get("items", [])
    for tl in lists:
        tasks = []
        token = None
        while True:
            data = svc.tasks().tasks().list(
                tasklist=tl["id"], maxResults=100, showCompleted=True,
                showHidden=True, pageToken=token,
            ).execute()
            tasks.extend(data.get("items", []))
            token = data.get("nextPageToken")
            if not token:
                break
        result.append({"tasklist": tl, "tasks": tasks})
    _json(out / "tasks.json", result)
    if progress_cb: progress_cb(1.0, f"Tareas · {sum(len(x["tasks"]) for x in result)} tareas")
    return {"tasklists": len(lists), "tasks": sum(len(x["tasks"]) for x in result)}


def _backup_drive(svc, out, options=None, progress_cb=None):
    options = normalize_backup_options(options)["drive"]
    files = []
    token = None
    while True:
        data = svc.files().list(
            q="trashed = false", pageSize=1000, pageToken=token,
            fields="nextPageToken,files(id,name,mimeType,description,createdTime,modifiedTime,size,parents,webViewLink,owners,permissions,starred,trashed,md5Checksum,fileExtension,capabilities)",
            orderBy="modifiedTime desc",
        ).execute()
        files.extend(data.get("files", []))
        token = data.get("nextPageToken")
        if not token:
            break
    if options["metadata"] or options["content"]:
        _json(out / "drive_files.json", files)

    max_mb = float(os.environ.get("ZAR_GOOGLE_BACKUP_MAX_FILE_MB", "25"))
    max_bytes = int(max_mb * 1024 * 1024)
    content_dir = out / "drive_content"
    if options["content"]:
        content_dir.mkdir(exist_ok=True)
    downloaded = 0
    skipped_large = 0
    native = {
        "application/vnd.google-apps.document": "application/pdf",
        "application/vnd.google-apps.spreadsheet": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.google-apps.presentation": "application/pdf",
    }
    for pos, f in enumerate(files, 1):
        fid = f.get("id")
        size = int(f.get("size") or 0)
        mime = f.get("mimeType", "")
        if not fid:
            continue
        if not options["content"]:
            if progress_cb: progress_cb(pos / max(1, len(files)), f"Drive · metadatos {pos}/{len(files)}")
            continue
        if size > max_bytes and mime not in native:
            skipped_large += 1
            continue
        try:
            buf = BytesIO()
            if mime in native:
                export_mime = native[mime]
                request = svc.files().export_media(fileId=fid, mimeType=export_mime)
                ext = ".pdf" if export_mime == "application/pdf" else ".xlsx"
            else:
                request = svc.files().get_media(fileId=fid)
                ext = Path(f.get("name") or "file").suffix or ".bin"
            downloader = MediaIoBaseDownload(buf, request, chunksize=1024 * 1024)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            target = content_dir / f"{_safe_name(fid)}_{_safe_name(f.get('name'))}{ext}"
            target.write_bytes(buf.getvalue())
            downloaded += 1
            if progress_cb: progress_cb(pos / max(1, len(files)), f"Drive · archivo {pos}/{len(files)}")
        except Exception as exc:
            f["backup_error"] = str(exc)
    _json(out / "drive_files.json", files)
    if progress_cb: progress_cb(1.0, f"Drive · {len(files)} archivos")
    return {"drive_files": len(files), "drive_downloaded": downloaded, "drive_skipped_large": skipped_large}


def _index_backup(out, stats, options=None):
    options = normalize_backup_options(options)
    """Index the useful structured snapshot into Zar's offline knowledge base."""
    try:
        from .knowledge import index_source
    except Exception:
        return {"indexed": 0, "index_error": "knowledge module unavailable"}
    indexed = 0
    errors = 0
    # Gmail
    try:
        if not (out / "messages.json").exists():
            raise FileNotFoundError
        messages = json.loads((out / "messages.json").read_text(encoding="utf-8"))
        max_index = int(os.environ.get("ZAR_GOOGLE_BACKUP_INDEX_MAX_MESSAGES", "50000"))
        for msg in messages[:max_index]:
            subject = _header(msg, "Subject")
            sender = _header(msg, "From")
            date = _header(msg, "Date")
            text = _message_text(msg)
            content = f"Fecha: {date}\nDe: {sender}\nPara: {_header(msg,'To')}\nAsunto: {subject}\n\n{text}"[:60000]
            index_source("google_gmail", msg.get("id"), f"Gmail · {subject or '(sin asunto)'}", content, {"thread_id": msg.get("threadId"), "label_ids": msg.get("labelIds", [])})
            indexed += 1
    except Exception:
        errors += 1
    # Contacts
    try:
        if not (out / "contacts.json").exists():
            raise FileNotFoundError
        contacts = json.loads((out / "contacts.json").read_text(encoding="utf-8"))
        for person in contacts:
            names = person.get("names") or []
            title = (names[0].get("displayName") if names else None) or "Contacto"
            content = json.dumps(person, ensure_ascii=False)
            index_source("google_contact", person.get("resourceName") or title, f"Contacto · {title}", content)
            indexed += 1
    except Exception:
        errors += 1
    # Calendar
    try:
        if not (out / "calendar.json").exists():
            raise FileNotFoundError
        calendars = json.loads((out / "calendar.json").read_text(encoding="utf-8"))
        for group in calendars:
            cal = group.get("calendar", {})
            for event in group.get("events", []):
                eid = event.get("id") or f"{cal.get('id')}:{event.get('summary')}:{event.get('start')}"
                title = event.get("summary") or "Evento de Calendar"
                content = json.dumps({"calendar": cal, "event": event}, ensure_ascii=False)
                index_source("google_calendar", eid, f"Calendar · {title}", content)
                indexed += 1
    except Exception:
        errors += 1
    # Tasks
    try:
        if not (out / "tasks.json").exists():
            raise FileNotFoundError
        groups = json.loads((out / "tasks.json").read_text(encoding="utf-8"))
        for group in groups:
            tl = group.get("tasklist", {})
            for task in group.get("tasks", []):
                tid = task.get("id") or f"{tl.get('id')}:{task.get('title')}"
                title = task.get("title") or "Tarea"
                content = json.dumps({"tasklist": tl, "task": task}, ensure_ascii=False)
                index_source("google_task", tid, f"Tarea · {title}", content)
                indexed += 1
    except Exception:
        errors += 1
    # Drive metadata + extracted content, keeping raw files in the backup tree.
    try:
        if not (out / "drive_files.json").exists():
            raise FileNotFoundError
        files = json.loads((out / "drive_files.json").read_text(encoding="utf-8"))
        for f in files:
            title = f.get("name") or "Archivo de Drive"
            index_source("google_drive", f.get("id") or title, f"Drive · {title}", json.dumps(f, ensure_ascii=False), f)
            indexed += 1
        try:
            from .knowledge import extract_text
            content_dir = out / "drive_content"
            if content_dir.exists():
                for path in content_dir.iterdir():
                    if not path.is_file():
                        continue
                    text = extract_text(path)
                    if text and text.strip():
                        index_source("google_drive_content", str(path), f"Contenido Drive · {path.name}", text[:200000], {"backup_path": str(path)})
                        indexed += 1
        except Exception:
            errors += 1
    except Exception:
        errors += 1
    # Index text-bearing Gmail attachments too, so an old invoice/PDF can be
    # found even while Google is disconnected.
    try:
        from .knowledge import extract_text
        attachment_dir = out / "gmail_attachments"
        if attachment_dir.exists():
            for path in attachment_dir.iterdir():
                if not path.is_file():
                    continue
                text = extract_text(path)
                if text and text.strip():
                    index_source("google_gmail_attachment", str(path), f"Adjunto Gmail · {path.name}", text[:200000], {"backup_path": str(path)})
                    indexed += 1
    except Exception:
        errors += 1
    try:
        index_source("google_backup_manifest", out.name, "Copia de seguridad Google", json.dumps(stats, ensure_ascii=False), {"path": str(out)})
        indexed += 1
    except Exception:
        errors += 1
    return {"indexed": indexed, "index_errors": errors}


def _set_service_progress(frac, message, total_services, service_idx):
    with _LOCK:
        total = max(1, int(total_services or 1))
        base = ((service_idx - 1) / total) * 80
        span = 80 / total
        _LAST["progress"] = round(base + max(0, min(1, float(frac or 0))) * span)
        _LAST["message"] = message
        _LAST["current_service"] = message.split(" · ", 1)[0]

def _run_backup(reason="google_connected", user_id=None, options=None):
    global _LAST
    user_id = user_id or get_current_user()
    options = normalize_backup_options(options)
    if not _has_backup_selection(options):
        raise RuntimeError("No has seleccionado ningún bloque de datos para la copia.")
    set_current_user(user_id)
    with _LOCK:
        _LAST = {"status": "running", "started_at": datetime.now(timezone.utc).isoformat(), "finished_at": None, "path": None, "error": None, "progress": 0, "current_service": "Preparando", "completed_services": 0, "total_services": 0, "message": "Preparando la copia de seguridad…", "service_states": {}, "options": options}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = _backup_root(user_id) / stamp
    out.mkdir(parents=True, exist_ok=True)
    try:
        creds = get_credentials(auto_refresh=True)
        if not creds:
            raise RuntimeError("No hay credenciales Google válidas para crear la copia.")
        svcs = _services(creds)
        stats = {"started_at": _LAST["started_at"], "reason": reason}
        service_errors = {}

        # Each Google service is backed up independently. A quota/rate-limit
        # error in Gmail must not abort Contacts, Calendar, Tasks or Drive.
        # This is especially important because Gmail's messages.list can hit
        # the per-user quota while the other APIs remain perfectly usable.
        service_plan = []
        if options["gmail"]["messages"] or options["gmail"]["drafts"] or options["gmail"]["attachments"]:
            service_plan.append(("gmail", "Gmail", lambda: _backup_gmail(svcs["gmail"], out, options, lambda frac, msg: _set_service_progress(frac, msg, total_services, idx))))
        if options["contacts"]:
            service_plan.append(("contacts", "Contactos", lambda: _backup_contacts(svcs["people"], out, options, lambda frac, msg: _set_service_progress(frac, msg, total_services, idx))))
        if options["calendar"]:
            service_plan.append(("calendar", "Calendar", lambda: _backup_calendar(svcs["calendar"], out, options, lambda frac, msg: _set_service_progress(frac, msg, total_services, idx))))
        if options["tasks"]:
            service_plan.append(("tasks", "Tareas", lambda: _backup_tasks(svcs["tasks"], out, options, lambda frac, msg: _set_service_progress(frac, msg, total_services, idx))))
        if options["drive"]["metadata"] or options["drive"]["content"]:
            service_plan.append(("drive", "Drive", lambda: _backup_drive(svcs["drive"], out, options, lambda frac, msg: _set_service_progress(frac, msg, total_services, idx))))
        total_services = len(service_plan)
        with _LOCK:
            _LAST["total_services"] = total_services
            _LAST["options"] = options
        for idx, (key, label, fn) in enumerate(service_plan, 1):
            with _LOCK:
                _LAST["current_service"] = label
                _LAST["message"] = f"Copiando {label}…"
                _LAST["progress"] = round(((idx - 1) / total_services) * 80)
                _LAST["completed_services"] = idx - 1
            try:
                stats.update(fn())
                with _LOCK:
                    _LAST["service_states"][key] = "done"
            except Exception as exc:
                service_errors[key] = str(exc)
                stats[f"{key}_error"] = str(exc)
                with _LOCK:
                    _LAST["service_states"][key] = "warning"
                # Leave an explicit empty snapshot for services that could not
                # be copied, while preserving all other successful services.
                if key == "gmail":
                    _json(out / "messages.json", [])
                    _json(out / "labels.json", [])
                    _json(out / "drafts.json", [])
                elif key == "contacts":
                    _json(out / "contacts.json", [])
                elif key == "calendar":
                    _json(out / "calendar.json", [])
                elif key == "tasks":
                    _json(out / "tasks.json", [])
                elif key == "drive":
                    _json(out / "drive_files.json", [])
            with _LOCK:
                _LAST["completed_services"] = idx
                _LAST["progress"] = round((idx / total_services) * 80)

        stats["service_errors"] = service_errors
        stats["backup_options"] = options
        with _LOCK:
            _LAST["current_service"] = "Indexando datos"
            _LAST["message"] = "Indexando la copia para poder consultarla sin conexión…"
            _LAST["progress"] = 85
        stats.update(_index_backup(out, stats, options))
        with _LOCK:
            _LAST["progress"] = 95
            _LAST["current_service"] = "Finalizando"
            _LAST["message"] = "Guardando manifiesto y preparando la copia local…"
        stats["finished_at"] = datetime.now(timezone.utc).isoformat()
        _json(out / "manifest.json", stats)
        _json(_backup_root(user_id) / "latest.json", {"path": str(out), "manifest": stats})
        final_status = "done_with_warnings" if service_errors else "done"
        with _LOCK:
            _LAST = {"status": final_status, "started_at": stats["started_at"], "finished_at": stats["finished_at"], "path": str(out), "error": None, "stats": stats, "progress": 100, "current_service": "Completada", "completed_services": total_services, "total_services": total_services, "message": "Copia de seguridad completada." if not service_errors else "Copia completada con incidencias; revisa los servicios marcados.", "service_states": dict(_LAST.get("service_states") or {}), "options": options}
    except Exception as exc:
        with _LOCK:
            _LAST = {"status": "error", "started_at": _LAST.get("started_at"), "finished_at": datetime.now(timezone.utc).isoformat(), "path": str(out), "error": str(exc), "progress": int(_LAST.get("progress") or 0), "current_service": _LAST.get("current_service"), "completed_services": int(_LAST.get("completed_services") or 0), "total_services": int(_LAST.get("total_services") or 5), "message": "La copia se ha detenido por un error.", "service_states": dict(_LAST.get("service_states") or {})}


def start_google_backup(reason="google_connected", user_id=None, options=None):
    """Start a non-blocking full snapshot after Google authentication succeeds."""
    user_id = user_id or get_current_user()
    with _LOCK:
        if _LAST.get("status") == "running":
            return {"started": False, "reason": "already_running"}
    t = threading.Thread(target=_run_backup, args=(reason, user_id, options), daemon=True, name="zar-google-backup")
    t.start()
    return {"started": True, "reason": reason}


def backup_status():
    with _LOCK:
        return dict(_LAST)


def maybe_start_google_backup(max_age_hours=24):
    """Refresh the snapshot when Zar is opened and the last one is stale."""
    try:
        latest = _backup_root() / "latest.json"
        if not latest.exists():
            if get_credentials(auto_refresh=True):
                return start_google_backup("stale_or_missing")
            return {"started": False, "reason": "not_connected"}
        data = json.loads(latest.read_text(encoding="utf-8"))
        finished = (data.get("manifest") or {}).get("finished_at")
        if finished:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(finished.replace("Z", "+00:00"))).total_seconds() / 3600
            if age < max_age_hours:
                return {"started": False, "reason": "fresh", "age_hours": round(age, 2)}
        if get_credentials(auto_refresh=True):
            return start_google_backup("stale_or_missing")
    except Exception as exc:
        return {"started": False, "reason": "error", "error": str(exc)}
    return {"started": False, "reason": "not_connected"}
