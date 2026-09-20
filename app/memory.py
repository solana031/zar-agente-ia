import json
from pathlib import Path
from datetime import datetime

import os
DATA = Path(os.environ.get('ZAR_DATA_DIR', str(Path(__file__).resolve().parent.parent / 'data')))
DATA.mkdir(exist_ok=True)
MEMORY_FILE = DATA / "memory.json"
HISTORY_FILE = DATA / "chat_history.json"
CONVERSATION_FILE = DATA / "conversation.json"

from .user_scope import safe_slug

def _user_file(name):
    d = DATA / "users" / safe_slug()
    d.mkdir(parents=True, exist_ok=True)
    return d / name

def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

def memories():
    return load(_user_file("memory.json"), load(MEMORY_FILE, []))

def remember(text):
    item = {"id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
            "text": text,
            "created_at": datetime.now().isoformat(timespec="seconds")}
    data = memories()
    data.append(item)
    save(_user_file("memory.json"), data)
    try:
        from .knowledge import index_memory
        index_memory(item["id"], item["text"], meta={"provenance": "user_explicit", "memory_version": 2})
    except Exception:
        pass
    try:
        from .memory3 import upsert
        upsert(item["id"], item["text"], source="user_explicit")
    except Exception:
        pass
    return item

def delete_memory(memory_id):
    data = [m for m in memories() if m.get("id") != memory_id]
    save(_user_file("memory.json"), data)
    try:
        from .knowledge import delete_source
        delete_source("memory", memory_id)
    except Exception:
        pass
    try:
        from .memory3 import delete as delete_memory3
        delete_memory3(memory_id)
    except Exception:
        pass
    return data

def history():
    return load(_user_file("chat_history.json"), load(HISTORY_FILE, []))

def add_message(role, content):
    data = history()
    data.append({"role": role, "content": content,
                 "created_at": datetime.now().isoformat(timespec="seconds")})
    save(_user_file("chat_history.json"), data)
    try:
        from .knowledge import index_message
        index_message(role, content)
    except Exception:
        pass


def conversation():
    return load(_user_file("conversation.json"), load(CONVERSATION_FILE, []))

def add_conversation_message(role, content):
    data = conversation()
    data.append({"role": role, "content": content, "created_at": datetime.now().isoformat(timespec="seconds")})
    # Keep active context compact enough for prompts while retaining the current thread.
    data = data[-40:]
    save(_user_file("conversation.json"), data)

def _threads_file():
    return _user_file("conversations.json")

def archive_current_conversation(title=None):
    current = conversation()
    if not current:
        return None
    threads = load(_threads_file(), [])
    if not isinstance(threads, list): threads = []
    first = next((x.get("content") for x in current if x.get("role") == "user" and x.get("content")), "Conversación")
    item = {
        "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
        "title": (title or first or "Conversación")[:90],
        "created_at": current[0].get("created_at") if current else datetime.now().isoformat(timespec="seconds"),
        "updated_at": current[-1].get("created_at") if current else datetime.now().isoformat(timespec="seconds"),
        "messages": current,
    }
    threads.append(item)
    threads = threads[-200:]
    save(_threads_file(), threads)
    return item

def list_conversations(limit=50):
    threads = load(_threads_file(), [])
    if not isinstance(threads, list): return []
    out=[]
    for x in reversed(threads[-max(1,int(limit)):]):
        out.append({k:x.get(k) for k in ("id","title","created_at","updated_at")})
    return out

def get_conversation_archive(thread_id):
    for x in load(_threads_file(), []):
        if x.get("id") == thread_id:
            return x
    return None

def clear_conversation(archive=True):
    if archive:
        archive_current_conversation()
    save(_user_file("conversation.json"), [])
