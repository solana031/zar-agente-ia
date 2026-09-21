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
_LAST = {"status": "never", "started_at": None, "finished_at": None, "path": None, "error": None}


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


def _backup_gmail(svc, out):
    items = []
    token = None
    max_attachments_mb = float(os.environ.get("ZAR_GOOGLE_BACKUP_MAX_ATTACHMENT_MB", "25"))
    max_attachment_bytes = int(max_attachments_mb * 1024 * 1024)
    attachment_dir = out / "gmail_attachments"
    attachment_dir.mkdir(exist_ok=True)
    attachments_downloaded = 0
    attachments_skipped = 0

    while True:
        data = svc.users().messages().list(
            userId="me", maxResults=500, includeSpamTrash=True, pageToken=token
        ).execute()
        for ref in data.get("messages", []):
            msg = svc.users().messages().get(userId="me", id=ref["id"], format="full").execute()
            items.append(msg)
            # Preserve actual attachments when Google exposes an attachmentId.
            for part in _walk_parts(msg.get("payload", {})):
                filename = part.get("filename")
                attachment_id = (part.get("body") or {}).get("attachmentId")
                if not filename or not attachment_id:
                    continue
                size = int((part.get("body") or {}).get("size") or 0)
                if size > max_attachment_bytes:
                    attachments_skipped += 1
                    continue
                try:
                    att = svc.users().messages().attachments().get(
                        userId="me", messageId=msg["id"], id=attachment_id
                    ).execute()
                    data64 = att.get("data", "")
                    raw = base64.urlsafe_b64decode(data64 + "=" * (-len(data64) % 4))
                    target = attachment_dir / f"{_safe_name(msg['id'])}_{_safe_name(filename)}"
                    target.write_bytes(raw)
                    attachments_downloaded += 1
                except Exception:
                    attachments_skipped += 1
        token = data.get("nextPageToken")
        if not token:
            break

    _json(out / "messages.json", items)
    _json(out / "labels.json", svc.users().labels().list(userId="me").execute().get("labels", []))
    try:
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
    except Exception:
        drafts = []
    profile = svc.users().getProfile(userId="me").execute()
    _json(out / "profile.json", profile)
    return {"messages": len(items), "gmail_labels": len(json.loads((out / "labels.json").read_text())), "drafts": len(drafts), "gmail_attachments_downloaded": attachments_downloaded, "gmail_attachments_skipped": attachments_skipped}


def _backup_contacts(svc, out):
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
    return {"contacts": len(people)}


def _backup_calendar(svc, out):
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
    return {"calendars": len(calendars), "events": sum(len(x["events"]) for x in result)}


def _backup_tasks(svc, out):
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
    return {"tasklists": len(lists), "tasks": sum(len(x["tasks"]) for x in result)}


def _backup_drive(svc, out):
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
    _json(out / "drive_files.json", files)

    max_mb = float(os.environ.get("ZAR_GOOGLE_BACKUP_MAX_FILE_MB", "25"))
    max_bytes = int(max_mb * 1024 * 1024)
    content_dir = out / "drive_content"
    content_dir.mkdir(exist_ok=True)
    downloaded = 0
    skipped_large = 0
    native = {
        "application/vnd.google-apps.document": "application/pdf",
        "application/vnd.google-apps.spreadsheet": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.google-apps.presentation": "application/pdf",
    }
    for f in files:
        fid = f.get("id")
        size = int(f.get("size") or 0)
        mime = f.get("mimeType", "")
        if not fid:
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
        except Exception as exc:
            f["backup_error"] = str(exc)
    _json(out / "drive_files.json", files)
    return {"drive_files": len(files), "drive_downloaded": downloaded, "drive_skipped_large": skipped_large}


def _index_backup(out, stats):
    """Index the useful structured snapshot into Zar's offline knowledge base."""
    try:
        from .knowledge import index_source
    except Exception:
        return {"indexed": 0, "index_error": "knowledge module unavailable"}
    indexed = 0
    errors = 0
    # Gmail
    try:
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


def _run_backup(reason="google_connected", user_id=None):
    global _LAST
    user_id = user_id or get_current_user()
    set_current_user(user_id)
    with _LOCK:
        _LAST = {"status": "running", "started_at": datetime.now(timezone.utc).isoformat(), "finished_at": None, "path": None, "error": None}
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
        for key, fn, empty_files in [
            ("gmail", lambda: _backup_gmail(svcs["gmail"], out), []),
            ("contacts", lambda: _backup_contacts(svcs["people"], out), []),
            ("calendar", lambda: _backup_calendar(svcs["calendar"], out), []),
            ("tasks", lambda: _backup_tasks(svcs["tasks"], out), []),
            ("drive", lambda: _backup_drive(svcs["drive"], out), []),
        ]:
            try:
                stats.update(fn())
            except Exception as exc:
                service_errors[key] = str(exc)
                stats[f"{key}_error"] = str(exc)
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

        stats["service_errors"] = service_errors
        stats.update(_index_backup(out, stats))
        stats["finished_at"] = datetime.now(timezone.utc).isoformat()
        _json(out / "manifest.json", stats)
        _json(_backup_root(user_id) / "latest.json", {"path": str(out), "manifest": stats})
        final_status = "done_with_warnings" if service_errors else "done"
        with _LOCK:
            _LAST = {"status": final_status, "started_at": stats["started_at"], "finished_at": stats["finished_at"], "path": str(out), "error": None, "stats": stats}
    except Exception as exc:
        with _LOCK:
            _LAST = {"status": "error", "started_at": _LAST.get("started_at"), "finished_at": datetime.now(timezone.utc).isoformat(), "path": str(out), "error": str(exc)}


def start_google_backup(reason="google_connected", user_id=None):
    """Start a non-blocking full snapshot after Google authentication succeeds."""
    user_id = user_id or get_current_user()
    with _LOCK:
        if _LAST.get("status") == "running":
            return {"started": False, "reason": "already_running"}
    t = threading.Thread(target=_run_backup, args=(reason, user_id), daemon=True, name="zar-google-backup")
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
