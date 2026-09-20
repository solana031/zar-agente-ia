
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from .user_scope import safe_slug

DATA_DIR = Path(os.environ.get("ZAR_DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = DATA_DIR / "active_context.json"

def _state_file():
    d = DATA_DIR / "users" / safe_slug()
    d.mkdir(parents=True, exist_ok=True)
    return d / "active_context.json"
LOCK = threading.RLock()
DEFAULT = {
    "active_email": None,
    "pending_email": None,
    "saved_draft_id": "",
    "last_summary": "",
    "pending_calendar": None,
    "focus": {"type": "", "label": ""},
    "task": {"intent": "", "object_type": "", "object_id": "", "action": "", "risk": "", "status": "", "summary": "", "updated_at": ""},
    "last_uploaded_file": None,
    "pending_workspace": None,
    "last_workspace": None,
    "last_contact": None,
    "pending_contact": None,
    "last_media": None,
    "last_video_project": None,
}

def _load():
    with LOCK:
        try:
            data = json.loads(_state_file().read_text(encoding="utf-8"))
            out = DEFAULT.copy()
            out.update(data if isinstance(data, dict) else {})
            return out
        except (FileNotFoundError, json.JSONDecodeError):
            return DEFAULT.copy()

def _save(data):
    with LOCK:
        path = _state_file()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

def get_context():
    return _load()

def set_active_email(email):
    data = _load(); data["active_email"] = email; _save(data); return data

def set_pending_email(draft):
    data = _load(); data["pending_email"] = draft; data["saved_draft_id"] = ""; _save(data); return data

def mark_saved_draft(draft_id):
    data = _load(); data["saved_draft_id"] = draft_id or ""; _save(data); return data

def clear_pending(keep_email=True):
    data = _load(); data["pending_email"] = None; data["saved_draft_id"] = ""; 
    if not keep_email: data["active_email"] = None; data["last_summary"] = ""
    _save(data); return data

def set_summary(summary):
    data = _load(); data["last_summary"] = summary or ""; _save(data); return data

def set_focus(focus_type, label=""):
    data = _load(); data["focus"] = {"type": focus_type or "", "label": label or ""}; _save(data); return data

def clear_focus():
    data = _load(); data["focus"] = {"type": "", "label": ""}; _save(data); return data

def set_task_state(intent="", object_type="", object_id="", action="", risk="", status="", summary=""):
    data = _load()
    data["task"] = {
        "intent": intent or "", "object_type": object_type or "", "object_id": object_id or "",
        "action": action or "", "risk": risk or "", "status": status or "",
        "summary": summary or "", "updated_at": datetime.now(timezone.utc).isoformat()
    }
    _save(data); return data

def clear_task_state():
    return set_task_state()

def reset_context(clear_email=True):
    data = DEFAULT.copy()
    if not clear_email:
        old = _load(); data["active_email"] = old.get("active_email"); data["last_summary"] = old.get("last_summary", "")
    _save(data); return data


def set_pending_calendar(value):
    data = _load(); data["pending_calendar"] = value; _save(data); return data

def clear_pending_calendar():
    data = _load(); data["pending_calendar"] = None; _save(data); return data


def set_last_uploaded_file(item):
    data = _load(); data["last_uploaded_file"] = item; _save(data); return data

def clear_last_uploaded_file():
    data = _load(); data["last_uploaded_file"] = None; _save(data); return data


def set_pending_workspace(value):
    data = _load(); data["pending_workspace"] = value; _save(data); return data

def clear_pending_workspace():
    data = _load(); data["pending_workspace"] = None; _save(data); return data


def set_last_workspace(value):
    data = _load(); data["last_workspace"] = value; _save(data); return data


def clear_last_workspace():
    data = _load(); data["last_workspace"] = None; _save(data); return data


def set_last_contact(value):
    data = _load(); data["last_contact"] = value; _save(data); return data


def clear_last_contact():
    data = _load(); data["last_contact"] = None; _save(data); return data


def set_pending_contact(value):
    data = _load(); data["pending_contact"] = value; _save(data); return data


def clear_pending_contact():
    data = _load(); data["pending_contact"] = None; _save(data); return data


def set_media(platform, query, url):
    data = _load()
    data["last_media"] = {"platform": platform or "", "query": query or "", "url": url or "", "updated_at": datetime.now(timezone.utc).isoformat()}
    _save(data)
    return data


def set_last_video_project(project):
    data = _load(); data["last_video_project"] = project; _save(data); return data

def clear_last_video_project():
    data = _load(); data["last_video_project"] = None; _save(data); return data
