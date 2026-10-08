"""Resumable client for DramaClaw's official /api/v1 REST API.

Contract: dramaclaw/dramaclaw@a35f758e9c8821ba130bdd731ac88c8f52e7c566,
api/routes and api/schemas.py. Each advance performs at most one mutation.
The caller must serialize advances and persist checkpoints durably.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import requests

SOURCE_COMMIT = "a35f758e9c8821ba130bdd731ac88c8f52e7c566"
STAGES = ("project", "configure", "upload", "ingest", "episodes", "characters",
          "identities", "portraits", "identity_images", "script", "colors",
          "storyboard", "detect", "optimize", "frames", "narrator", "audio",
          "videos", "compose", "export", "done")
REPEATING = {"portraits", "identity_images", "frames", "videos"}
ACTIVE = {"pending", "submitting", "queued", "running"}


class DramaClawError(Exception):
    """Sanitized error safe for responses; never contains provider bodies."""
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _origin_url(value):
    value = str(value or "").strip().rstrip("/")
    p = urlsplit(value)
    if (p.scheme not in {"http", "https"} or not p.netloc or p.username
            or p.password or p.query or p.fragment):
        raise DramaClawError("configuration", "Configura una URL HTTP(S) de DramaClaw sin credenciales.")
    if p.path.rstrip("/") == "/api/v1":
        value = urlunsplit((p.scheme, p.netloc, "", "", ""))
    elif p.path not in {"", "/"}:
        raise DramaClawError("configuration", "La URL de DramaClaw debe ser su origen o terminar en /api/v1.")
    return value.rstrip("/")


def _part(value):
    value = str(value or "")
    if not value or value in {".", ".."} or "/" in value or "\\" in value or any(ord(c) < 32 for c in value):
        raise DramaClawError("contract", "DramaClaw devolvió un identificador no válido.")
    return quote(value, safe="")


class DramaClawClient:
    def __init__(self, base_url, token=None, timeout=20, session=None, public_url=None):
        self.base_url = _origin_url(base_url)
        self.public_url = _origin_url(public_url or base_url)
        self.timeout = min(max(float(timeout), 1), 120)
        self.session = session or requests.Session()
        self.headers = {"Accept": "application/json"}
        if token:
            self.headers["Authorization"] = "Bearer " + str(token)

    def _request(self, method, path, *, timeout=None, **kwargs):
        if not path.startswith("/") or path.startswith("//") or ".." in path.split("/"):
            raise DramaClawError("contract", "Ruta de DramaClaw no válida.")
        try:
            response = self.session.request(method, self.base_url + path,
                headers=self.headers, timeout=timeout or (min(self.timeout, 10), self.timeout),
                allow_redirects=False, **kwargs)
        except requests.RequestException:
            raise DramaClawError("connection", "No se pudo confirmar la respuesta de DramaClaw.") from None
        if not 200 <= response.status_code < 300:
            status = int(response.status_code)
            message = "DramaClaw no confirmó la operación. Revisa el proyecto en su editor."
            if status in {401, 403}:
                message = "DramaClaw rechazó el acceso. Revisa su autenticación y permisos."
            elif status in {404, 410}:
                message = "La versión conectada de DramaClaw no ofrece esta ruta o recurso."
            elif status == 429:
                message = "DramaClaw alcanzó un límite. Revisa el centro de tareas antes de continuar."
            raise DramaClawError("http_%s" % status, message)
        try:
            payload = response.json()
        except (ValueError, TypeError):
            raise DramaClawError("contract", "DramaClaw devolvió una respuesta no válida.") from None
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise DramaClawError("prerequisite", "DramaClaw requiere revisar configuración, modelos, voces o recursos del proyecto.")
        return payload

    def _get(self, path, **kwargs):
        return self._request("GET", "/api/v1" + path, **kwargs).get("data")

    def health(self):
        """Read-only auth/API check: at most two GETs, each with a 3 s timeout."""
        try:
            user = self._get("/auth/me", timeout=3)
            projects = self._get("/projects", timeout=3)
            if not isinstance(user, dict) or not isinstance(projects, list):
                raise DramaClawError("contract", "La respuesta no coincide con la API oficial de DramaClaw.")
            return {"ready": True, "status": "ready", "error": "", "api_contract": "api/v1",
                    "source_commit": SOURCE_COMMIT, "message": "API accesible; los modelos y cuotas se validarán al generar."}
        except DramaClawError as exc:
            return {"ready": False, "status": "error", "code": exc.code, "error": str(exc), "message": str(exc)}

    @staticmethod
    def _brief_bytes(brief):
        text = brief if isinstance(brief, str) else json.dumps(brief, ensure_ascii=False, sort_keys=True, indent=2)
        if not text.strip():
            raise DramaClawError("brief", "Falta el brief maestro completo.")
        # Structured ingest requires a chapter boundary; preserve the full brief.
        return ("第1章\n\n" + text).encode("utf-8")

    def _project(self, cp):
        return "/projects/" + _part(cp["project_id"])

    def _episode(self, cp):
        return self._project(cp) + "/episodes/" + str(int(cp.get("episode", 1)))

    def _save(self, cp, persist):
        cp["progress"] = round(STAGES.index(cp["stage"]) / (len(STAGES) - 1) * 100, 1) if cp["stage"] in STAGES else 0
        if cp.get("status") == "running":
            cp.pop("error", None)
            cp.pop("error_code", None)
        if cp.get("project_id"):
            cp["editor_url"] = self.public_url + self._project(cp) + "/episodes"
        persist(cp)
        return cp

    def _next(self, cp, persist, stage=None):
        cp["stage"] = stage or STAGES[STAGES.index(cp["stage"]) + 1]
        cp["status"] = "done" if cp["stage"] == "done" else "running"
        if cp["stage"]!="configure":cp["submission_state"]="READY" if cp["stage"]=="done" else "PROCESSING"
        for key in ("error", "error_code", "pending", "active_task", "active_tasks"):
            cp.pop(key, None)
        return self._save(cp, persist)

    def _blocked(self, cp, persist, code, message):
        cp.update(status="blocked", error_code=code, error=message,submission_state="UNKNOWN" if code=="submission_unknown" else "FAILED")
        return self._save(cp, persist)

    def _tasks(self, cp):
        data = self._get(self._project(cp) + "/tasks")
        if not isinstance(data, list):
            raise DramaClawError("contract", "DramaClaw no devolvió una lista de tareas válida.")
        return [item for item in data if isinstance(item, dict)]

    @staticmethod
    def _task_record(data, intent):
        task_id = data.get("task_id")
        if not isinstance(task_id, str) or not task_id or len(task_id) > 200:
            raise DramaClawError("contract", "DramaClaw no confirmó el identificador de la tarea.")
        if data.get("task_type", intent["task_type"]) != intent["task_type"]:
            raise DramaClawError("contract", "DramaClaw devolvió un tipo de tarea inesperado.")
        return {"task_id": task_id, "task_type": intent["task_type"],
                "episode": intent.get("episode", 0), "beat_num": intent.get("beat_num"),
                "scope": data.get("scope") or intent.get("scope"), "stage": intent["stage"],
                "target": intent.get("target", {}), "status": data.get("status", "queued")}

    def _accept(self, cp, persist, response, intent):
        if intent.get("task_type") == "sketch_grid_generation":
            items = (response.get("data") or {}).get("tasks")
            if not isinstance(items, list) or not items:
                raise DramaClawError("contract", "DramaClaw no confirmó las tareas de storyboard.")
            records = []
            for item in items:
                if not isinstance(item, dict) or not str(item.get("scope") or "").startswith("grid_"):
                    raise DramaClawError("contract", "DramaClaw no confirmó el scope de storyboard.")
                records.append(self._task_record(item, intent))
            cp["active_tasks"] = records
            cp.setdefault("tasks", []).extend(dict(r) for r in records)
            cp["partial_submission"] = bool((response.get("data") or {}).get("rejected"))
            cp.pop("pending", None)
            cp["status"] = "running"
            return self._save(cp, persist)
        if intent.get("task_type"):
            record = self._task_record(response, intent)
            cp["active_task"] = record
            cp.setdefault("tasks", []).append(dict(record))
            cp.pop("pending", None)
            cp["status"] = "running"
            return self._save(cp, persist)
        if intent["stage"] == "project":
            data = response.get("data") or {}
            identifier=data.get('project_id') or data.get('id')
            if not identifier:
                ids={key:data[key] for key in ('job_id','task_id','submission_id') if isinstance(data.get(key),str) and data[key]}
                if ids:
                    cp['submission_ids']=ids;cp['pending']['accepted']=True;cp['submission_state']='REQUEST_ACCEPTED'
                    return self._save(cp,persist)
                raise DramaClawError('project_response','DramaClaw no confirmó un proyecto ni una tarea de creación.')
            cp["project_id"] = identifier
            _part(cp["project_id"])
            cp['submission_state']='PROJECT_CREATED'
        if intent["stage"] == "narrator":
            cp["narrator_provider"] = intent.get("provider", "external")
        return self._next(cp, persist)

    def _submit(self, cp, persist, path, *, body=None, files=None, form=None,
                task_type=None, episode=0, beat_num=None, scope=None, target=None,
                method="POST", provider=None):
        target = target or {}
        if task_type and any(t.get("stage") == cp["stage"] and t.get("target") == target
                             and (cp["stage"] in REPEATING or t.get("scope") == scope)
                             and t.get("status") == "completed" for t in cp.get("tasks", [])):
            return self._blocked(cp, persist, "result_missing", "La tarea terminó pero falta su recurso. Revísalo en DramaClaw antes de generar otra vez.")
        before = [item.get("task_id") for item in self._tasks(cp)] if task_type else []
        intent = {"stage": cp["stage"], "task_type": task_type, "episode": episode,
                  "beat_num": beat_num, "scope": scope, "target": target,
                  "before_task_ids": before, "provider": provider}
        cp.update(pending=intent, status="running")
        self._save(cp, persist)  # Durable intention precedes every mutation.
        options = {"json": body if body is not None else {}}
        if files is not None:
            options = {"files": files, "data": form or {}}
        try:
            response = self._request(method, "/api/v1" + path, **options)
            return self._accept(cp, persist, response, intent)
        except DramaClawError as exc:
            # Even a 5xx may follow a queued operation. Keep intent, no retry.
            cp["last_submission_error"] = exc.code
            cp["submission_message"] = str(exc)
            if exc.code.startswith('http_') and exc.code[5:].isdigit() and 400 <= int(exc.code[5:]) < 500 and exc.code not in {'http_408','http_409'}:
                cp.pop('pending', None)
                return self._blocked(cp, persist, exc.code, str(exc))
            return self._save(cp, persist)

    def _beats(self, cp):
        data = self._get(self._episode(cp) + "/beats")
        if not isinstance(data, list):
            raise DramaClawError("contract", "DramaClaw no devolvió los planos del episodio.")
        return [b for b in data if isinstance(b, dict) and isinstance(b.get("beat_number"), int) and b["beat_number"] > 0]

    def _evidence(self, cp, stage, target=None):
        """Inspect resources which survive the server's one-hour task TTL."""
        target = target or {}
        if stage == "project":
            projects = self._get("/projects") or []
            found = [p for p in projects if isinstance(p, dict) and p.get("name") == cp["project_name"]]
            if len(found) == 1:
                cp["project_id"] = found[0].get("project_id") or found[0].get("id")
                _part(cp["project_id"])
                return True
            return False
        root, ep = self._project(cp), self._episode(cp)
        if stage == "configure":
            config = self._get(root) or {}
            return all(config.get(k) == v for k, v in cp["project_config"].items())
        if stage in {"ingest", "episodes", "identities"}:
            episodes = self._get(root + "/episodes") or []
            if stage == "identities":
                return any(e.get("number") == cp.get("episode", 1) and e.get("identity_ids") for e in episodes)
            return bool(episodes)
        if stage in {"characters", "portraits"}:
            chars = self._get(root + "/characters") or []
            return bool(chars) if stage == "characters" else any(c.get("name") == target.get("name") and c.get("portrait_url") for c in chars)
        if stage == "identity_images":
            items = self._get(root + "/characters/" + _part(target["name"]) + "/identities") or []
            return any(i.get("identity_id") == target.get("identity_id") and i.get("image_url") for i in items)
        if stage == "colors":
            return bool((self._get(ep + "/script") or {}).get("sketch_colors"))
        if stage == "narrator":
            return bool((self._get(root + "/narrator-voice") or {}).get("reference_url"))
        if stage in {"compose", "export"}:
            if stage=='compose' and cp.get('force_compose'):return False
            return (self._get(ep + "/final") or {}).get("exists") is True
        if stage == "upload":
            return False  # No promised upload-list/hash endpoint; never guess.
        beats = self._beats(cp)
        if target.get("beat_num"):
            beats = [b for b in beats if b["beat_number"] == target["beat_num"]]
        if not beats:
            return False
        if stage == "script":
            return all(b.get("narration_segment") or b.get("narration") or b.get("visual_description") for b in beats)
        if stage == "detect":
            return all(b.get("detected_identities") is not None or b.get("detected_props") is not None for b in beats)
        if stage == "optimize":
            return all(b.get("video_mode") and b.get("video_prompt") for b in beats)
        field = {"storyboard": "sketch_url", "frames": "frame_url", "audio": "audio_url", "videos": "video_url"}.get(stage)
        return bool(field) and all(b.get(field) for b in beats)

    def _completed(self, cp, persist, record):
        if record['stage']=='videos':
            cp['forced_video_beats']=[x for x in cp.get('forced_video_beats',[]) if x!=record.get('beat_num')]
        if record['stage']=='compose':cp.pop('force_compose',None)
        for task in cp.get("tasks", []):
            if task["task_id"] == record["task_id"]:
                task["status"] = "completed"
        cp.pop("active_task", None)
        cp.pop("pending", None)
        if record["stage"] in REPEATING or record["stage"] == "episodes":
            cp["status"] = "running"
            return self._save(cp, persist)
        return self._next(cp, persist)

    def _poll(self, cp, persist):
        record = cp["active_task"]
        found = next((t for t in self._tasks(cp) if t.get("task_id") == record["task_id"]), None)
        if found is None:
            if self._evidence(cp, record["stage"], record.get("target")):
                return self._completed(cp, persist, record)
            return self._blocked(cp, persist, "task_missing", "La tarea no figura en DramaClaw y su resultado no está confirmado. Revisa el editor antes de reintentar.")
        status = found.get("status")
        if status == "completed":
            return self._completed(cp, persist, record)
        if status in ACTIVE:
            record["status"] = status
            cp["status"] = "running"
            return self._save(cp, persist)
        if status in {"failed", "cancelled"}:
            record["status"] = status
            if self._evidence(cp, record["stage"], record.get("target")):
                return self._completed(cp, persist, record)
            reason=str(found.get('error') or '').lower()
            hint=('ACTION_REQUIRED: DramaClaw no tiene configuradas sus credenciales DramaClawAPI de generación.' if 'api key not set' in reason else 'DramaClaw agotó la cuota del proveedor; revisa saldo/cuota antes de reintentar.' if 'quota' in reason or 'insufficient credits' in reason else 'DramaClaw detuvo la etapa. Revisa modelos, voces, cuotas y recursos en su editor; ZAR conserva los identificadores.')
            return self._blocked(cp, persist, "task_" + status, hint)
        return self._blocked(cp, persist, "task_status", "Estado de tarea desconocido; no se enviará otra generación.")

    def _poll_batch(self, cp, persist):
        remote = {t.get("task_id"): t for t in self._tasks(cp)}
        unknown, failed, running = False, False, False
        for record in cp["active_tasks"]:
            task = remote.get(record["task_id"])
            state = task.get("status") if task else None
            record["status"] = state or record.get("status", "unknown")
            for saved in cp.get("tasks", []):
                if saved["task_id"] == record["task_id"]:
                    saved["status"] = record["status"]
            running = running or state in ACTIVE
            failed = failed or state in {"failed", "cancelled"}
            unknown = unknown or state not in ACTIVE | {"completed", "failed", "cancelled"}
        if running:
            cp["status"] = "running"
            return self._save(cp, persist)
        if self._evidence(cp, "storyboard"):
            return self._next(cp, persist)
        code = "storyboard_failed" if failed else "storyboard_incomplete"
        if unknown:
            code = "task_missing"
        return self._blocked(cp, persist, code, "Faltan planos del storyboard. Revisa las tareas de DramaClaw; ZAR conserva todos los IDs y no repetirá la generación completa.")

    def _recover(self, cp, persist):
        intent = cp["pending"]
        if self._evidence(cp, intent["stage"], intent.get("target")):
            if intent["stage"] in REPEATING or intent["stage"] == "episodes":
                cp.pop("pending", None)
                cp["status"] = "running"
                return self._save(cp, persist)
            return self._next(cp, persist)
        if intent['stage']=='project' and intent.get('accepted'):
            cp['status']='running';cp['submission_state']='PROCESSING'
            return self._save(cp,persist)
        rejected=cp.get('last_submission_error','')
        if rejected.startswith('http_') and rejected[5:].isdigit() and 400<=int(rejected[5:])<500 and rejected not in {'http_408','http_409'}:
            cp.pop('pending',None)
            return self._blocked(cp,persist,rejected,cp.get('submission_message') or 'DramaClaw rechazó la solicitud (HTTP '+rejected[5:]+'); revisa la petición antes de reintentar.')
        if intent.get("task_type"):
            def matches(task):
                if task.get("task_id") in intent.get("before_task_ids", []):
                    return False
                if task.get("task_type") != intent["task_type"] or task.get("episode") != intent["episode"]:
                    return False
                if intent.get("beat_num") is not None and task.get("beat_num") != intent["beat_num"]:
                    return False
                if intent.get("scope") and task.get("scope") != intent["scope"]:
                    return False
                if intent["stage"] == "frames":
                    digest = hashlib.sha1(str(intent["target"]["beat_num"]).encode()).hexdigest()[:12]
                    return str(task.get("scope") or "").endswith("__" + digest)
                return True
            candidates = [t for t in self._tasks(cp) if matches(t)]
            if intent["stage"] == "storyboard" and candidates:
                return self._accept(cp, persist, {"data": {"tasks": candidates}}, intent)
            if len(candidates) == 1:
                return self._accept(cp, persist, candidates[0], intent)
        return self._blocked(cp, persist, "submission_unknown", "No se puede confirmar si DramaClaw aceptó la operación. " + cp.get('submission_message', '') + " Se conserva su intención y no se repetirá automáticamente; revisa el editor.")

    def advance(self, checkpoint, master_brief, persist, narrator=None):
        """One bounded advance; narrator() returns (audio bytes, MIME, provider)."""
        cp = checkpoint
        cp.setdefault("stage", "project")
        cp.setdefault("status", "running")
        cp.setdefault("tasks", [])
        try:
            if cp["stage"] not in STAGES:
                raise DramaClawError("checkpoint", "Checkpoint de DramaClaw no válido.")
            content = self._brief_bytes(master_brief)
            digest = hashlib.sha256(content).hexdigest()
            binding = hashlib.sha256(self.base_url.encode()).hexdigest()
            if cp.get("brief_sha256", digest) != digest or cp.get("origin_sha256", binding) != binding:
                raise DramaClawError("checkpoint", "El brief o el servidor cambiaron; crea una producción nueva para conservar la trazabilidad.")
            cp.setdefault("brief_sha256", digest)
            cp.setdefault("origin_sha256", binding)
            cp.setdefault("project_name", "ZAR_" + uuid.uuid4().hex[:20])
            # Official validate_project_name only accepts letters/digits/underscore.
            # Repair only a proven rejected legacy creation, never an ambiguous one.
            if cp['stage']=='project' and cp.get('last_submission_error')=='http_400' and '-' in cp['project_name'] and not cp.get('project_id'):
                cp['project_name']=cp['project_name'].replace('-','_');cp.pop('pending',None)
                cp.pop('last_submission_error',None);cp.pop('submission_message',None)
                self._save(cp,persist)
            cp.setdefault("filename", "zar-brief-" + digest[:16] + ".txt")
            cp.setdefault("episode", 1)
            cp.setdefault("project_config", {"spine_template": "narrated", "narration_style": "third_person", "aspect_ratio": "9:16", "add_subtitles": True})
            if cp["stage"] == "done":
                return self._save(cp, persist)
            if cp.get("pending"):
                return self._recover(cp, persist)
            if cp.get("active_tasks"):
                return self._poll_batch(cp, persist)
            if cp.get("active_task"):
                return self._poll(cp, persist)
            cp["status"] = "running"
            cp.pop("error", None)
            stage = cp["stage"]
            if stage == "project":
                return self._submit(cp, persist, "/projects", body={"name": cp["project_name"]})
            root, ep, number = self._project(cp), self._episode(cp), cp["episode"]
            if stage == "configure":
                return self._submit(cp, persist, root, body=cp["project_config"], method="PATCH")
            if stage == "upload":
                return self._submit(cp, persist, root + "/ingest/upload", files={"file": (cp["filename"], content, "text/plain; charset=utf-8")}, form={"spine_template": "narrated"})
            if stage == "ingest":
                return self._submit(cp, persist, root + "/ingest/start", body={"filename": cp["filename"]}, task_type="ingest_fast")
            if stage == "episodes":
                items = self._get(root + "/episodes") or []
                if items:
                    if len(items) != 1:
                        return self._blocked(cp, persist, "multiple_episodes", "El brief produjo varios episodios. Revisa su alcance en DramaClaw antes de generar el vídeo.")
                    cp["episode"] = int(items[0]["number"])
                    return self._next(cp, persist)
                return self._submit(cp, persist, root + "/episodes/plan", body={"target_episodes": 1, "planning_mode": "chapters"}, task_type="build_episodes")
            if stage == "characters":
                if self._evidence(cp, stage):
                    return self._next(cp, persist)
                return self._submit(cp, persist, root + "/characters/build", task_type="build_characters")
            if stage == "identities":
                if self._evidence(cp, stage):
                    return self._next(cp, persist)
                return self._submit(cp, persist, ep + "/identities/plan", task_type="identity_planner", episode=number)
            if stage == "portraits":
                for char in self._get(root + "/characters") or []:
                    if not char.get("portrait_url"):
                        name = char["name"]
                        return self._submit(cp, persist, root + "/characters/" + _part(name) + "/portrait-async", task_type="character_portrait", scope="character:" + name + ":portrait", target={"name": name})
                return self._next(cp, persist)
            if stage == "identity_images":
                eps = self._get(root + "/episodes") or []
                selected = next((e for e in eps if e.get("number") == number), {})
                required = set(selected.get("identity_ids") or [])
                chars = self._get(root + "/characters") or []
                cursor = int(cp.get("identity_character_cursor", 0))
                if cursor >= len(chars):
                    cp.pop("identity_character_cursor", None)
                    return self._next(cp, persist)
                name = chars[cursor]["name"]
                items = self._get(root + "/characters/" + _part(name) + "/identities") or []
                for ident in items:
                    if ident.get("identity_id") in required and not ident.get("image_url"):
                        return self._submit(cp, persist, root + "/characters/" + _part(name) + "/identities/" + _part(ident["identity_id"]) + "/generate-async", task_type="identity_image", scope="character:" + name + ":identity:" + ident["identity_name"], target={"name": name, "identity_id": ident["identity_id"]})
                cp["identity_character_cursor"] = cursor + 1
                return self._save(cp, persist)
            if stage == "script":
                if self._evidence(cp, stage):
                    return self._next(cp, persist)
                return self._submit(cp, persist, ep + "/script/generate", task_type="script_writer", episode=number)
            if stage == "colors":
                if self._evidence(cp, stage):
                    return self._next(cp, persist)
                return self._submit(cp, persist, ep + "/sketches/assign-colors")
            if stage == "storyboard":
                if self._evidence(cp, stage):
                    return self._next(cp, persist)
                return self._submit(cp, persist, ep + "/sketches/generate", body={"grid_index": -1, "aspect_ratio": "2:3"}, task_type="sketch_grid_generation", episode=number)
            if stage == "detect":
                if self._evidence(cp, stage):
                    return self._next(cp, persist)
                return self._submit(cp, persist, ep + "/sketches/detect-identities")
            if stage == "optimize":
                if self._evidence(cp, stage):
                    return self._next(cp, persist)
                return self._submit(cp, persist, ep + "/optimize/video-global", task_type="global_optimize_video", episode=number)
            if stage == "frames":
                for beat in self._beats(cp):
                    if not beat.get("frame_url"):
                        bn = beat["beat_number"]
                        return self._submit(cp, persist, ep + "/beats/regenerate", body={"beat_indices": [bn], "mode_key": "1x1_2-3"}, task_type="selected_regen", episode=number, target={"beat_num": bn})
                return self._next(cp, persist)
            if stage == "narrator":
                if self._evidence(cp, stage):
                    return self._next(cp, persist)
                if narrator is None:
                    return self._blocked(cp, persist, "narrator_required", "Configura una voz de narrador en ZAR o carga una muestra en DramaClaw.")
                if cp.get("narrator_intent"):
                    return self._blocked(cp, persist, "narrator_unknown", "La generación anterior de la muestra de voz no se confirmó. Revisa el proveedor antes de generar otra.")
                cp["narrator_intent"] = True
                self._save(cp, persist)
                try:
                    result = narrator()
                    if result is None:
                        cp.pop("narrator_intent", None)
                        return self._blocked(cp, persist, "narrator_required", "Configura una voz de narrador en ZAR o carga una muestra en DramaClaw.")
                    audio, mime, provider = result
                except Exception:
                    return self._blocked(cp, persist, "narrator_failed", "No se pudo confirmar la muestra del narrador. Revisa las voces de ZAR o carga una muestra en DramaClaw.")
                extensions = {"audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/wav": "wav", "audio/x-wav": "wav", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/aac": "aac"}
                if not isinstance(audio, bytes) or not audio or mime not in extensions:
                    return self._blocked(cp, persist, "narrator_format", "La muestra del narrador no tiene un formato admitido.")
                return self._submit(cp, persist, root + "/narrator-voice/upload", files={"file": ("zar-narrator." + extensions[mime], audio, mime)}, provider=("elevenlabs" if str(provider).lower().startswith("elevenlabs") else "f5" if str(provider).lower().startswith("f5") else "gemini" if str(provider).lower().startswith("gemini") else "external"))
            if stage == "audio":
                if self._evidence(cp, stage):
                    return self._next(cp, persist)
                return self._submit(cp, persist, ep + "/audio/generate", body={"mode": "sync_changed"}, task_type="audio_generation_indextts2", episode=number)
            if stage == "videos":
                for beat in self._beats(cp):
                    if not beat.get("video_url") or beat.get('beat_number') in cp.get('forced_video_beats',[]):
                        config = self._get(root) or {}
                        options = self._get(root + "/video-backends") or []
                        allowed = [o for o in options if isinstance(o, dict) and not o.get("dialogue_only")]
                        choice = next((o for o in allowed if o.get("value") == config.get("video_backend")), None)
                        if choice is None:
                            choice = next((o for o in allowed if o.get("is_default")), None)
                        if choice is None:
                            return self._blocked(cp, persist, "video_backend", "Selecciona en DramaClaw un modelo de vídeo compatible con narración.")
                        resolution = config.get("video_resolution") or "720x1280"
                        choices = choice.get("resolution_options") or []
                        if choices and resolution not in choices:
                            if cp.get('project_config',{}).get('video_resolution'):
                                return self._blocked(cp,persist,'video_resolution','El backend elegido no admite el formato solicitado; selecciona un backend compatible en DramaClaw.')
                            resolution = choices[0]
                        bn = beat["beat_number"]
                        return self._submit(cp, persist, ep + "/beats/" + str(bn) + "/video", body={"video_backend": choice["value"], "resolution": resolution}, task_type="single_video", episode=number, beat_num=bn, target={"beat_num": bn})
                return self._next(cp, persist)
            if stage == "compose":
                if self._evidence(cp, stage):
                    return self._next(cp, persist)
                config = cp.get('project_config') or {}
                return self._submit(cp, persist, ep + "/videos/compose", body={"add_subtitles": config.get('add_subtitles', True), "add_bgm": cp.get('music', False), "resolution": config.get('video_resolution', "720x1280")}, task_type="compose_episode", episode=number)
            if stage == "export":
                final = self._get(ep + "/final") or {}
                filename = "ep%03d_final.mp4" % number
                if final.get("exists") is not True or final.get("filename") != filename:
                    return self._blocked(cp, persist, "final_missing", "DramaClaw no confirmó un vídeo final compuesto.")
                p = urlsplit(str(final.get("video_url") or ""))
                expected = "/static/projects/" + _part(cp["project_id"]) + "/videos/episodes/" + filename
                if p.username or p.password or p.fragment or p.path != expected or (p.netloc and (p.scheme + "://" + p.netloc) not in {self.base_url, self.public_url}):
                    return self._blocked(cp, persist, "final_url", "La URL no corresponde al origen configurado y al vídeo final esperado.")
                cp["video_url"] = self.public_url + expected
                cp["download_url"] = self.public_url + "/api/v1" + ep + "/export/video"
                cp["subtitle_url"] = self.public_url + "/api/v1" + ep + "/export/srt"
                cp["source_commit"] = SOURCE_COMMIT
                return self._next(cp, persist, "done")
        except DramaClawError as exc:
            return self._blocked(cp, persist, exc.code, str(exc))
        except (KeyError, ValueError, TypeError, IndexError):
            return self._blocked(cp, persist, "contract", "La respuesta de DramaClaw no coincide con el contrato esperado. Revisa la versión y el proyecto.")
        return self._blocked(cp, persist, "stage", "No se pudo resolver la etapa de DramaClaw.")

    def download_final(self, checkpoint, path, max_bytes=512 * 1024 * 1024):
        """Stream only the official export endpoint, atomically, no redirects."""
        if checkpoint.get("stage") != "done" or not checkpoint.get("video_url"):
            raise DramaClawError("final_missing", "No hay vídeo final confirmado para descargar.")
        binding = hashlib.sha256(self.base_url.encode()).hexdigest()
        if checkpoint.get("origin_sha256") != binding:
            raise DramaClawError("checkpoint", "El servidor no coincide con el origen de esta producción.")
        endpoint = self.base_url + "/api/v1" + self._episode(checkpoint) + "/export/video"
        destination = Path(path)
        partial = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".part")
        response = None
        try:
            response = self.session.request("GET", endpoint, headers=self.headers,
                timeout=(10, 60), allow_redirects=False, stream=True)
            if response.status_code != 200:
                raise DramaClawError("download", "DramaClaw no confirmó la descarga del vídeo final.")
            content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if content_type not in {"video/mp4", "application/octet-stream"}:
                raise DramaClawError("download_type", "La exportación de DramaClaw no es un MP4.")
            expected_length = int(response.headers.get("Content-Length") or 0)
            if expected_length > max_bytes:
                raise DramaClawError("download_size", "El MP4 supera el límite de descarga de ZAR.")
            destination.parent.mkdir(parents=True, exist_ok=True)
            size, prefix = 0, b""
            with partial.open("xb") as output:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > max_bytes:
                        raise DramaClawError("download_size", "El MP4 supera el límite de descarga de ZAR.")
                    if len(prefix) < 32:
                        prefix = (prefix + chunk)[:32]
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if expected_length and size != expected_length:
                raise DramaClawError("download_incomplete", "La descarga del MP4 quedó incompleta.")
            if size < 12 or prefix[4:8] != b"ftyp":
                raise DramaClawError("download_type", "El archivo descargado no contiene una cabecera MP4 válida.")
            os.replace(partial, destination)
            return {"path": str(destination), "bytes": size, "mime": "video/mp4"}
        except (requests.RequestException, OSError, ValueError):
            raise DramaClawError("download", "No se pudo completar la descarga del MP4 de DramaClaw.") from None
        finally:
            if response is not None:
                response.close()
            if partial.exists():
                partial.unlink()
