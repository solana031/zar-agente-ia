"""ZAR Skills 1.0 — habilidades reutilizables y persistentes.

Las habilidades son procedimientos creados por el usuario. Se almacenan en el
espacio persistente de cada usuario y nunca se incluyen en los ZIP de release.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
import os

from .user_scope import safe_slug, get_current_user

DATA_DIR = Path(os.environ.get("ZAR_DATA_DIR", "/data"))


def _dir():
    d = DATA_DIR / "users" / safe_slug() / "skills"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _file():
    return _dir() / "skills.json"


def _load():
    try:
        value = json.loads(_file().read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def _save(items):
    target = _file()
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)


def _clean_list(value, separator=None, limit=30, item_limit=1000):
    if isinstance(value, str):
        parts = value.split(separator) if separator else value.splitlines()
    else:
        parts = value or []
    return [str(x).strip()[:item_limit] for x in parts if str(x).strip()][:limit]


def list_skills():
    return sorted(
        _load(),
        key=lambda x: (not bool(x.get("enabled", True)), (x.get("name") or "").lower()),
    )


def get_skill(skill_id):
    return next((x for x in _load() if x.get("id") == skill_id), None)


def create_skill(data):
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValueError("La habilidad necesita un nombre.")
    steps = _clean_list(data.get("steps"), limit=30)
    triggers = _clean_list(data.get("triggers"), separator=",", limit=20, item_limit=160)
    tools = _clean_list(data.get("tools"), separator=",", limit=30, item_limit=80)
    now = time.time()
    item = {
        "id": uuid.uuid4().hex,
        "name": name[:100],
        "description": str(data.get("description") or "").strip()[:1000],
        "steps": steps,
        "tools": tools,
        "triggers": triggers,
        "category": str(data.get("category") or "procedure").strip()[:40],
        "learning_id": str(data.get("learning_id") or "").strip()[:80],
        "enabled": bool(data.get("enabled", True)),
        "created_at": now,
        "updated_at": now,
        "owner": get_current_user(),
        "use_count": 0,
    }
    items = _load()
    items.append(item)
    _save(items)
    return item


def update_skill(skill_id, data):
    items = _load()
    for item in items:
        if item.get("id") != skill_id:
            continue
        if "name" in data:
            name = str(data.get("name") or "").strip()
            if not name:
                raise ValueError("La habilidad necesita un nombre.")
            item["name"] = name[:100]
        if "description" in data:
            item["description"] = str(data.get("description") or "").strip()[:1000]
        if "steps" in data:
            item["steps"] = _clean_list(data.get("steps"), limit=30)
        if "tools" in data:
            item["tools"] = _clean_list(data.get("tools"), separator=",", limit=30, item_limit=80)
        if "triggers" in data:
            item["triggers"] = _clean_list(data.get("triggers"), separator=",", limit=20, item_limit=160)
        if "category" in data:
            item["category"] = str(data.get("category") or "procedure").strip()[:40]
        if "learning_id" in data:
            item["learning_id"] = str(data.get("learning_id") or "").strip()[:80]
        if "enabled" in data:
            item["enabled"] = bool(data.get("enabled"))
        item["updated_at"] = time.time()
        _save(items)
        return item
    return None


def delete_skill(skill_id):
    items = _load()
    new = [x for x in items if x.get("id") != skill_id]
    if len(new) == len(items):
        return False
    _save(new)
    return True


def _norm(text):
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def match_skill(message):
    """Detecta una invocación suficientemente explícita para ejecutar una habilidad."""
    text = _norm(message)
    if not text:
        return None
    explicit = bool(re.search(r"\b(ejecuta|ejecutar|usa|utiliza|aplica|lanza|haz|hace|prepara|realiza)\b", text))
    for skill in list_skills():
        if not skill.get("enabled", True):
            continue
        name = _norm(skill.get("name"))
        triggers = [_norm(x) for x in skill.get("triggers", [])]
        if explicit and name and name in text:
            return skill
        if explicit and any(t and t in text for t in triggers):
            return skill
    return None


def build_execution_prompt(skill, user_message):
    steps = "\n".join(
        f"{i + 1}. {s}" for i, s in enumerate(skill.get("steps") or [])
    ) or "(sin pasos predefinidos; resuelve la tarea con criterio)"
    tools = ", ".join(skill.get("tools") or []) or "las herramientas disponibles de ZAR"
    learned = ""
    if skill.get("learning_id"):
        try:
            from .learning import context_for
            learned = context_for(skill.get("name") or "", max_chars=9000)
        except Exception:
            learned = ""
    return (
        "ESTÁS EJECUTANDO UNA HABILIDAD GUARDADA DE ZAR.\n"
        f"Nombre: {skill.get('name')}\n"
        f"Descripción: {skill.get('description') or '(sin descripción)'}\n"
        f"Categoría: {skill.get('category') or 'procedure'}\n"
        f"Herramientas previstas: {tools}\n"
        "Procedimiento de la habilidad:\n"
        + steps
        + ("\n\nCONOCIMIENTO APRENDIDO RELEVANTE:\n" + learned if learned else "")
        + "\n\nReglas de ejecución: primero identifica la tarea concreta y después usa las herramientas reales de ZAR "
        "cuando correspondan. Verifica los resultados de las herramientas antes de afirmarlos. Respeta siempre "
        "las confirmaciones de seguridad para acciones externas; no envíes correos ni modifiques datos externos "
        "sin la confirmación que exige ZAR. Si la habilidad requiere información actual, consulta la web; si "
        "requiere un archivo, usa el archivo real. No inventes resultados, no modifiques el código de ZAR ni sus "
        "permisos y, si falta un dato imprescindible, pregúntalo.\n\n"
        "Orden original del usuario:\n"
        + (user_message or "")
    )


def execute_skill(skill_id, user_message, runner):
    skill = get_skill(skill_id)
    if not skill:
        raise ValueError("Habilidad no encontrada.")
    result = runner(build_execution_prompt(skill, user_message))
    items = _load()
    for item in items:
        if item.get("id") == skill_id:
            item["use_count"] = int(item.get("use_count", 0) or 0) + 1
            item["last_used_at"] = time.time()
            item["updated_at"] = time.time()
            break
    _save(items)
    return result, skill
