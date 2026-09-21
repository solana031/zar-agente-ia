"""ZAR Learning 2.0 — aprendizaje persistente, medible y reutilizable.

Convierte una petición explícita de aprendizaje en un proceso observable:
- investigación web por fases,
- fuentes deduplicadas,
- síntesis estructurada,
- conocimiento persistente recuperable por el agente,
- habilidad reutilizable,
- progreso, fuentes, tiempos y estado consultables desde la UI.

El aprendizaje no equivale a dominio absoluto: ZAR conserva un currículo y
pruebas de dominio para que el conocimiento pueda ampliarse y actualizarse.
"""
from __future__ import annotations
import json, os, re, time, uuid, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import requests

from .user_scope import safe_slug
from .skills import create_skill

DATA_DIR = Path(os.environ.get("ZAR_DATA_DIR", "/data"))


def _dir():
    d = DATA_DIR / "users" / safe_slug() / "learning"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _file():
    return _dir() / "learning.json"


def _load():
    try:
        v = json.loads(_file().read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else {"topics": {}, "jobs": {}}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"topics": {}, "jobs": {}}


def _save(v):
    p = _file(); tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def list_learning():
    return list(_load().get("topics", {}).values())


def _live_job(job):
    if not job:
        return job
    out = dict(job)
    if out.get("status") in ("queued", "researching", "synthesizing") and out.get("started_at"):
        out["elapsed_seconds"] = round(max(0, time.time() - float(out.get("started_at") or time.time())), 1)
    return out

def list_jobs():
    return [_live_job(x) for x in sorted(list(_load().get("jobs", {}).values()), key=lambda x: x.get("created_at", 0), reverse=True)[:30]]

def get_job(job_id):
    return _live_job(_load().get("jobs", {}).get(job_id))


def _set_job(job_id, **changes):
    d = _load(); job = d.setdefault("jobs", {}).setdefault(job_id, {"id": job_id})
    job.update(changes); job["updated_at"] = time.time(); _save(d); return job


def _gemini_key_model():
    try:
        from .config import load
        cfg = load()
    except Exception:
        cfg = {}
    return (
        str(cfg.get("api", {}).get("api_key", "") or os.environ.get("GEMINI_API_KEY", "")).strip(),
        str(cfg.get("api", {}).get("model", "gemini-3.6-flash") or "gemini-3.6-flash").strip(),
    )


def _synth(topic, goal, references, research):
    key, model = _gemini_key_model()
    fallback = {
        "summary": f"Plan práctico y verificable para aprender {topic} y aplicarlo a tareas reales de ZAR.",
        "curriculum": ["Fundamentos", "Herramientas", "Técnicas", "Casos reales", "Práctica", "Verificación", "Actualización"],
        "steps": [f"Estudiar fundamentos de {topic}", f"Practicar {topic} con casos reales", f"Comparar técnicas y buenas prácticas de {topic}", f"Aplicar lo aprendido con herramientas de ZAR", f"Verificar resultados y detectar errores", f"Actualizar el conocimiento cuando cambie el dominio"],
        "triggers": [f"ayúdame con {topic}", f"aplica lo aprendido en {topic}", topic],
        "tools": ["web", "memoria", "archivos", "investigación"],
        "mastery_checks": ["Explicar los conceptos clave", "Resolver un caso real", "Detectar errores", "Comparar alternativas", "Aplicar el conocimiento y verificar el resultado"],
        "limitations": ["El dominio depende del objetivo definido y de la calidad y actualidad de las fuentes."],
    }
    if not key:
        return fallback
    context = json.dumps(research, ensure_ascii=False)[:60000]
    prompt = (
        "Eres el planificador de aprendizaje persistente de ZAR. Diseña un currículo práctico y verificable; "
        "no afirmes dominio absoluto por leer unas pocas fuentes.\n"
        f"TEMA: {topic}\nOBJETIVO: {goal or 'aprenderlo con profundidad y poder aplicarlo'}\n"
        f"REFERENCIAS DEL USUARIO: {references or []}\nINVESTIGACIÓN:\n{context}\n"
        "Devuelve SOLO JSON: summary, curriculum (6-12 módulos), steps (8-20 acciones), triggers (3-8), "
        "tools (lista), mastery_checks (5-10 pruebas), limitations (lista), update_frequency. "
        "Distingue hechos de recomendaciones y señala incertidumbres."
    )
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        r = requests.post(url, params={"key": key}, json={"contents": [{"parts": [{"text": prompt}]}],
                           "generationConfig": {"temperature": 0.15, "responseMimeType": "application/json"}}, timeout=120)
        r.raise_for_status(); data = r.json(); text = ""
        for c in data.get("candidates", []):
            for part in (c.get("content") or {}).get("parts", []): text += part.get("text", "")
        text = re.sub(r"^```json\s*|\s*```$", "", text.strip(), flags=re.I)
        out = json.loads(text)
        for k, v in fallback.items(): out.setdefault(k, v)
        return out
    except Exception:
        return fallback


def _queries(topic, goal, refs):
    base = [
        f"{topic} guía completa fundamentos buenas prácticas",
        f"{topic} advanced techniques professional workflow",
        f"{topic} tutorial práctico casos reales errores comunes",
        f"{topic} estándares documentación oficial recursos de aprendizaje",
        f"{topic} herramientas actuales ejemplos profesionales",
        f"{topic} ejercicios prácticas verificación dominio",
    ]
    text = (topic + " " + (goal or "")).lower()
    if any(x in text for x in ("foto", "fotografía", "diseño", "imagen", "edición")):
        base += [f"{topic} Behance Dribbble profesionales referencias", f"{topic} Instagram profesionales tutorial"]
    if refs: base.append(" ".join(refs[:3]))
    # Limitamos deliberadamente la primera investigación para que sea rápida y medible.
    return base[:7]


def _search_one(q):
    """Perform one bounded live search.

    The learning engine must never depend on a long-lived daemon thread.  A
    single query is executed during a normal HTTP request and the result is
    persisted before the next query starts.  The preferred Google-grounded
    search gets a hard wall-clock budget; a public-search fallback gets its own
    budget.  If both time out, the query is recorded as failed and the engine
    moves on instead of freezing the whole learning job.
    """
    from .web_search import google_web_search, _fallback_web_search

    result = {"value": None}
    finished = threading.Event()

    def worker():
        try:
            result["value"] = google_web_search(
                q,
                instructions=(
                    "Recopila fuentes útiles para estudiar el tema; prioriza "
                    "documentación oficial, recursos educativos y referencias profesionales."
                ),
            )
        except Exception as exc:
            result["value"] = {"ok": False, "error": str(exc)}
        finally:
            finished.set()

    t = threading.Thread(target=worker, daemon=True, name="zar-learning-search")
    t.start()
    # Google grounding has its own network timeout, but a learning job must not
    # inherit that potentially long timeout.  We cap the wait at 12 seconds.
    if finished.wait(12):
        res = result.get("value") or {"ok": False, "error": "Sin resultado de búsqueda."}
    else:
        # Give the independent public fallback a separate short budget.  It is
        # also isolated so a network stall cannot block the learning request.
        fallback_result = {"value": None}
        fallback_done = threading.Event()
        def fallback_worker():
            try:
                fallback_result["value"] = _fallback_web_search(
                    q,
                    "Recopila resultados públicos útiles para estudiar el tema; prioriza fuentes fiables y educativas.",
                )
            except Exception as exc:
                fallback_result["value"] = {"ok": False, "error": str(exc)}
            finally:
                fallback_done.set()
        threading.Thread(target=fallback_worker, daemon=True, name="zar-learning-fallback").start()
        if fallback_done.wait(12):
            res = fallback_result.get("value") or {"ok": False, "error": "Sin resultado de búsqueda."}
        else:
            res = {"ok": False, "error": "La consulta superó el tiempo máximo y se omitió para mantener el aprendizaje activo."}

    return {
        "query": q,
        "ok": bool(res.get("ok")),
        "text": (res.get("text") or "")[:9000],
        "sources": res.get("sources") or [],
        "provider": res.get("provider") or "",
        "error": res.get("error") or "",
    }


def _lease_path(job_id):
    return _dir() / f"{job_id}.lease"


def _acquire_lease(job_id, max_age=90):
    """Cross-process best-effort lease so two browser polls cannot advance twice."""
    p = _lease_path(job_id)
    try:
        if p.exists() and time.time() - p.stat().st_mtime > max_age:
            p.unlink(missing_ok=True)
        fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(time.time()).encode("utf-8")); os.close(fd)
        return True
    except FileExistsError:
        return False
    except OSError:
        return False


def _release_lease(job_id):
    try:
        _lease_path(job_id).unlink(missing_ok=True)
    except OSError:
        pass


def _query_plan(topic, goal, references):
    return _queries(topic, goal, references)


def advance_learning(job_id):
    """Advance exactly one durable learning step and return the live job.

    This function is intentionally called by the status endpoint.  There is no
    background learning daemon: every completed search/synthesis step is
    persisted in ``learning.json``.  A process restart therefore resumes from
    the last persisted query instead of losing the worker.
    """
    if not _acquire_lease(job_id):
        return get_job(job_id)
    try:
        job = _load().get("jobs", {}).get(job_id)
        if not job:
            return None
        if job.get("status") in ("completed", "error", "cancelled", "paused"):
            return get_job(job_id)

        topic = str(job.get("topic") or "").strip()
        goal = str(job.get("goal") or "").strip()
        references = list(job.get("references") or [])
        qs = list(job.get("queries") or _query_plan(topic, goal, references))
        idx = int(job.get("query_index") or 0)
        started = float(job.get("started_at") or time.time())
        estimate = int(job.get("estimated_seconds") or max(90, len(qs) * 18 + 45))

        _set_job(job_id,
                 status="researching", phase="Investigando fuentes",
                 message=f"Investigando consulta {min(idx+1, len(qs))}/{len(qs)}…",
                 started_at=started, queries=qs, queries_total=len(qs),
                 query_index=idx, heartbeat_at=time.time(),
                 elapsed_seconds=round(time.time()-started, 1), estimated_seconds=estimate)

        if _cancel_requested(job_id):
            return get_job(job_id)

        research = list(job.get("research") or [])
        sources = list(job.get("sources") or [])

        if idx < len(qs):
            q = qs[idx]
            item = _search_one(q)
            research.append(item)
            sources.extend(item.get("sources") or [])
            clean_sources=[]; seen=set()
            for source in sources:
                u=source.get("url")
                if u and u not in seen:
                    seen.add(u); clean_sources.append(source)
            idx += 1
            progress = 8 + int(idx / max(1, len(qs)) * 60)
            msg = f"Consulta {idx}/{len(qs)} completada"
            if item.get("ok"):
                msg += f" · {len(item.get('sources') or [])} fuentes encontradas"
            else:
                msg += " · sin resultado utilizable; continúo con la siguiente"
            _set_job(job_id,
                     status="researching" if idx < len(qs) else "synthesizing",
                     progress=progress if idx < len(qs) else 70,
                     phase="Investigando fuentes" if idx < len(qs) else "Sintetizando conocimiento",
                     message=msg,
                     query_index=idx, queries_done=idx, queries_total=len(qs),
                     research=research, sources=clean_sources,
                     source_count=len(clean_sources), heartbeat_at=time.time(),
                     elapsed_seconds=round(time.time()-started, 1), estimated_seconds=estimate)
            if idx < len(qs):
                return get_job(job_id)
            job = _load().get("jobs", {}).get(job_id) or job
            research = list(job.get("research") or research)
            sources = list(job.get("sources") or clean_sources)

        # Synthesis is a separate durable phase.  If the process dies after this
        # request, the next poll sees "synthesizing" and retries synthesis.
        if _cancel_requested(job_id):
            return get_job(job_id)
        if job.get("status") == "synthesizing" or idx >= len(qs):
            _set_job(job_id, status="synthesizing", progress=72,
                     phase="Sintetizando conocimiento",
                     message=f"He reunido {len(sources)} fuentes. Organizando el conocimiento…",
                     source_count=len(sources), heartbeat_at=time.time(),
                     elapsed_seconds=round(time.time()-started, 1))
            plan = _synth(topic, goal, references, research)
            _set_job(job_id, progress=88, phase="Creando capacidad reutilizable",
                     message="Generando currículo, comprobaciones y habilidad…",
                     heartbeat_at=time.time(), elapsed_seconds=round(time.time()-started, 1))
            if _cancel_requested(job_id):
                return get_job(job_id)
            now=time.time(); learning_id=job.get("learning_id") or uuid.uuid4().hex
            knowledge_digest="\n\n".join([f"CONSULTA: {x.get('query')}\n{x.get('text','')}" for x in research])[:35000]
            skill_id=job.get("skill_id")
            if not skill_id:
                skill=create_skill({
                    "name": f"{topic[:80]} · aprendido por ZAR",
                    "description": plan.get("summary") or f"Capacidad aprendida sobre {topic}.",
                    "steps": plan.get("steps") or [],
                    "triggers": plan.get("triggers") or [topic],
                    "tools": plan.get("tools") or ["web", "memoria", "archivos", "investigación"],
                    "enabled": True, "category": "learned", "learning_id": learning_id,
                })
                skill_id=skill.get("id")
            topic_key=topic.lower()
            record={
                "id":learning_id,"topic":topic,"goal":goal,"references":references[:10],
                "status":"learned_initial","progress":100,"created_at":float(job.get("created_at") or now),"updated_at":now,
                "summary":plan.get("summary", ""),"curriculum":plan.get("curriculum", []),
                "mastery_checks":plan.get("mastery_checks", []),"limitations":plan.get("limitations", []),
                "update_frequency":plan.get("update_frequency", "cuando cambie el dominio o el usuario lo solicite"),
                "sources":sources[:60],"source_count":len(sources),"skill_id":skill_id,
                "knowledge_digest":knowledge_digest,"elapsed_seconds":round(now-started,1),
            }
            d=_load(); d.setdefault("topics",{})[topic_key]=record
            d.setdefault("jobs",{}).setdefault(job_id,{}).update({
                "status":"completed","progress":100,"phase":"Completado",
                "message":"Aprendizaje inicial completado; conocimiento y habilidad guardados.",
                "topic":topic,"result":record,"learning_id":learning_id,"skill_id":skill_id,
                "research":research,"sources":sources,"queries_done":len(qs),"queries_total":len(qs),
                "query_index":len(qs),"source_count":len(sources),"elapsed_seconds":round(now-started,1),
                "estimated_seconds":estimate,"updated_at":time.time()
            }); _save(d)
            return get_job(job_id)
        return get_job(job_id)
    except Exception as exc:
        if not _cancel_requested(job_id):
            _set_job(job_id,status="error",progress=100,phase="Error",message=str(exc)[:1200],elapsed_seconds=round(time.time()-float((_load().get("jobs",{}).get(job_id) or {}).get("started_at") or time.time()),1))
        return get_job(job_id)
    finally:
        _release_lease(job_id)

def _cancel_requested(job_id):
    job = _load().get("jobs", {}).get(job_id) or {}
    return bool(job.get("cancel_requested")) or job.get("status") == "cancelled"

def delete_learning(job_id):
    data = _load(); job = data.get("jobs", {}).get(job_id)
    if not job:
        return False
    status = job.get("status")
    topic = str(job.get("topic") or "").lower()
    if status in ("queued", "researching", "synthesizing"):
        job["cancel_requested"] = True; job["status"] = "cancelled"; job["phase"] = "Eliminado"
        job["message"] = "Aprendizaje eliminado por el usuario."; job["updated_at"] = time.time()
        data.setdefault("topics", {}).pop(topic, None); _save(data); return True
    result = job.get("result") or {}; skill_id = result.get("skill_id") or job.get("skill_id")
    data.get("jobs", {}).pop(job_id, None); data.setdefault("topics", {}).pop(topic, None); _save(data)
    if skill_id:
        try:
            from .skills import delete_skill; delete_skill(skill_id)
        except Exception: pass
    return True

def _run_job(*args, **kwargs):
    """Compatibility shim: legacy callers no longer launch a daemon worker."""
    return None


def start_learning(topic, goal="", references=None):
    topic=str(topic or "").strip()
    if not topic: raise ValueError("Indica qué quieres que aprenda ZAR.")
    references=[str(x).strip() for x in (references or []) if str(x).strip()][:10]
    job_id=uuid.uuid4().hex; now=time.time(); qs=_query_plan(topic,str(goal or "").strip(),references)
    estimate=max(90, len(qs)*18+45)
    _set_job(job_id,
             status="queued", progress=5, phase="En cola",
             message="Aprendizaje creado. ZAR iniciará la primera consulta al actualizar su estado.",
             topic=topic, goal=str(goal or "").strip(), references=references,
             queries=qs, query_index=0, queries_total=len(qs), queries_done=0,
             source_count=0, research=[], sources=[], created_at=now, updated_at=now,
             started_at=now, estimated_seconds=estimate, heartbeat_at=now,
             learning_id=uuid.uuid4().hex)
    # Advance the first step immediately in the same request, but without any
    # persistent background thread. If the network is slow, the job remains
    # safely persisted and the next status request continues it.
    return advance_learning(job_id)


def resume_learning(job_id):
    job=get_job(job_id)
    if not job: raise ValueError("Aprendizaje no encontrado.")
    if job.get("status")=="completed": return job
    topic=str(job.get("topic") or "").strip()
    if not topic: raise ValueError("El aprendizaje no tiene tema recuperable.")
    _set_job(job_id,status="queued",phase="Reanudando",message="Aprendizaje reanudado. Continuaré desde la última consulta guardada.",heartbeat_at=time.time(),cancel_requested=False)
    return advance_learning(job_id)

def learn_from_file(file_id):
    from .file_analysis import analyze_file
    result = analyze_file(file_id); analysis = result.get("analysis") or {}
    topic = str(analysis.get("document_type") or "documento adjunto")
    d = _load(); key = f"file:{file_id}"
    d.setdefault("topics", {})[key] = {
        "id": uuid.uuid4().hex, "topic": topic, "goal": "Aprender de la estructura y contenido del documento adjunto.",
        "status": "learned_from_document", "progress": 100, "created_at": time.time(), "updated_at": time.time(),
        "source_file_id": file_id, "analysis": analysis,
        "summary": analysis.get("summary") or analysis.get("description") or "",
    }
    _save(d); return {"ok": True, "learning": d["topics"][key], "analysis": analysis}


def active_learning_count():
    return sum(1 for x in list_learning() if x.get("status") in ("learning", "learned_initial", "learned", "learned_from_document"))


def context_for(query="", max_chars=9000):
    """Devuelve conocimiento aprendido relevante para inyectarlo en el agente."""
    q = re.findall(r"[\wáéíóúüñ]{4,}", (query or "").lower())
    topics = list_learning(); scored = []
    for t in topics:
        hay = " ".join([str(t.get("topic", "")), str(t.get("summary", "")), " ".join(t.get("curriculum") or [])]).lower()
        score = sum(1 for token in set(q) if token in hay)
        if score or not q: scored.append((score, t))
    scored.sort(key=lambda x: x[0], reverse=True)
    blocks=[]
    for _, t in scored[:4]:
        blocks.append(f"TEMA APRENDIDO: {t.get('topic')}\nRESUMEN: {t.get('summary','')}\nCURRÍCULO: {', '.join(t.get('curriculum') or [])}\nCOMPROBACIONES DE DOMINIO: {', '.join(t.get('mastery_checks') or [])}\nFUENTES: {t.get('source_count',0)}")
        if sum(map(len, blocks)) > max_chars: break
    return "\n\n".join(blocks)[:max_chars]
