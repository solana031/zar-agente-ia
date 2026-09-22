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

# Hard wall-clock budget for an initial learning session. The objective is to
# maximize useful knowledge, not to leave ZAR researching indefinitely.
MAX_LEARNING_SECONDS = 3600
SEARCH_TIMEOUT_SECONDS = 5
SYNTH_TIMEOUT_SECONDS = 25


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
    # Migrate legacy error records created by v30.10.4/v30.10.5 that could
    # incorrectly show 100% even though the learning had not completed.
    if out.get("status") == "error" and float(out.get("progress") or 0) >= 100:
        idx = int(out.get("query_index") or 0)
        total = max(1, int(out.get("queries_total") or len(out.get("queries") or []) or 1))
        out["progress"] = max(5, min(99, 8 + int(idx / total * 60)))
    if out.get("estimated_seconds"):
        out["estimated_seconds"] = min(MAX_LEARNING_SECONDS, max(60, int(float(out.get("estimated_seconds") or 0))))
    # Legacy sessions may have been started before the one-hour budget existed.
    # Do not expose an absurd remaining estimate; once the budget is exceeded,
    # the next worker pass will move to synthesis instead of continuing research.
    if out.get("status") in ("queued", "researching", "synthesizing") and out.get("started_at"):
        elapsed = float(out.get("elapsed_seconds") or 0)
        if elapsed >= MAX_LEARNING_SECONDS:
            out["estimated_seconds"] = MAX_LEARNING_SECONDS
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
                           "generationConfig": {"temperature": 0.15, "responseMimeType": "application/json"}}, timeout=SYNTH_TIMEOUT_SECONDS)
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
    """Build a compact, high-value curriculum search plan.

    The goal is breadth + practical usefulness, not seven slow serial searches.
    Six focused queries are enough for the first pass; they are processed in
    parallel batches and each failed route falls back to other legal/public
    sources, including manuals and legitimately accessible PDFs.
    """
    text = (topic + " " + (goal or "")).lower()
    base = [
        f"{topic} fundamentos avanzados buenas prácticas profesionales guía",
        f"{topic} composición exposición iluminación color técnicas profesionales",
        f"{topic} flujo de trabajo profesional retoque edición paso a paso",
        f"{topic} tutoriales manuales documentación oficial cursos PDF acceso legal",
        f"{topic} herramientas software profesionales tutorial Photoshop Lightroom CapCut Picsart",
        f"{topic} casos reales ejercicios errores comunes verificación conocimientos",
    ]
    if any(x in text for x in ("foto", "fotografía", "diseño", "imagen", "edición")):
        base[4] = f"{topic} Photoshop Lightroom Camera Raw CapCut Picsart tutorial profesional"
        base.append(f"{topic} fotógrafos profesionales referencias portafolios técnicas edición")
    if refs:
        base.append(" ".join(refs[:3]))
    return base[:6]


def _search_with_timeout(fn, *args, timeout=10, **kwargs):
    """Run one network search with a hard wall-clock budget."""
    result = {"value": None}
    done = threading.Event()

    def worker():
        try:
            result["value"] = fn(*args, **kwargs)
        except Exception as exc:
            result["value"] = {"ok": False, "error": str(exc)}
        finally:
            done.set()

    threading.Thread(target=worker, daemon=True, name="zar-learning-search").start()
    if done.wait(timeout):
        return result.get("value") or {"ok": False, "error": "Sin resultado de búsqueda."}
    return {"ok": False, "error": f"La búsqueda superó {timeout}s y se omite esta vía."}


def _learning_query_variants(q):
    """Generate legal/robust alternatives when the first web query is weak."""
    q = re.sub(r"\s+", " ", str(q or "").strip())
    if not q:
        return []
    return [
        q,
        f"{q} guía manual tutorial profesional",
        f"{q} filetype:pdf manual guía curso",
        f"{q} documentación oficial recursos educativos",
        f"{q} ebook acceso abierto técnicas avanzadas",
    ]


def _usable_result(res):
    if not isinstance(res, dict) or not res.get("ok"):
        return False
    rows = res.get("sources") or res.get("results") or []
    text = str(res.get("text") or "").strip()
    # A search is useful if it produced either actual source URLs or substantive
    # text. Prefer sources because they make the learned knowledge auditable.
    return bool(rows) or len(text) >= 180


def _merge_search_results(results):
    sources = []
    seen = set()
    texts = []
    providers = []
    for res in results:
        if not isinstance(res, dict):
            continue
        if res.get("provider"):
            providers.append(str(res.get("provider")))
        for s in (res.get("sources") or res.get("results") or []):
            if not isinstance(s, dict):
                continue
            u = str(s.get("url") or "").strip()
            if u and u not in seen:
                seen.add(u)
                sources.append({
                    "title": s.get("title") or u,
                    "url": u,
                    **({"snippet": s.get("snippet")} if s.get("snippet") else {}),
                })
        if res.get("text"):
            texts.append(str(res["text"])[:5000])
    return {
        "sources": sources[:20],
        "text": "\n\n".join(texts)[:12000],
        "provider": " + ".join(dict.fromkeys(providers)),
    }


def _search_one(q):
    """Search one learning query with a cascading fallback strategy.

    A failed/empty query is never treated as the end of the learning session.
    ZAR tries the original query, practical/manual variants, legitimate PDF/
    course/documentation variants, and finally the keyless public fallback.
    The engine records which route worked and moves to the next learning query
    even when every route for this one fails.
    """
    from .web_search import google_web_search, _fallback_web_search

    attempts = []
    variants = _learning_query_variants(q)
    # For professional topics, explicitly diversify the source ecosystem so a
    # weak search result never becomes a dead end. These are legal/public
    # resource targets, not piracy/download instructions.
    if any(token in q.lower() for token in ("fotograf", "edición", "imagen", "diseño")):
        variants.extend([
            f"{q} Adobe official documentation Lightroom Photoshop Camera Raw",
            f"{q} university course open textbook PDF legal",
            f"{q} public library ebook photography editing professional",
        ])

    for variant in variants[:3]:
        res = _search_with_timeout(
            google_web_search,
            variant,
            "Busca fuentes públicas y legales útiles para aprender el tema. "
            "Prioriza documentación oficial, manuales, cursos, universidades, "
            "editoriales, organizaciones profesionales y recursos educativos. "
            "Si existe material PDF accesible legalmente, inclúyelo. No uses "
            "copias pirateadas ni fuentes de descarga ilícita.",
            timeout=SEARCH_TIMEOUT_SECONDS,
        )
        attempts.append(res)
        if _usable_result(res):
            merged = _merge_search_results(attempts)
            return {
                "query": q, "ok": True,
                "text": merged["text"],
                "sources": merged["sources"],
                "provider": merged["provider"] or "Google Search grounding",
                "attempts": len(attempts),
                "fallback_used": len(attempts) > 1,
                "error": "",
            }

    # Keyless public search is the last independent route. Its implementation
    # may itself take longer than desired, so it is also bounded here.
    for variant in variants[3:6]:
        res = _search_with_timeout(
            _fallback_web_search,
            variant,
            "Busca resultados públicos legales, manuales, cursos y PDFs de acceso legítimo.",
            timeout=SEARCH_TIMEOUT_SECONDS,
        )
        attempts.append(res)
        if _usable_result(res):
            merged = _merge_search_results(attempts)
            return {
                "query": q, "ok": True,
                "text": merged["text"],
                "sources": merged["sources"],
                "provider": merged["provider"] or "Búsqueda pública alternativa",
                "attempts": len(attempts),
                "fallback_used": True,
                "error": "",
            }

    errors = [str(x.get("error") or "") for x in attempts if isinstance(x, dict) and x.get("error")]
    return {
        "query": q, "ok": False,
        "text": "",
        "sources": [],
        "provider": "",
        "attempts": len(attempts),
        "fallback_used": True,
        "error": ("Todas las vías de búsqueda fallaron; continuaré con la siguiente consulta. "
                  + (" | ".join(errors[:3]) if errors else "Sin resultado utilizable.")),
    }


# Durable-in-process worker. State is persisted after every batch, so a
# Railway restart can recover by simply calling the status/resume endpoint.
_learning_workers = {}
_learning_workers_lock = threading.Lock()

def _ensure_learning_worker(job_id):
    with _learning_workers_lock:
        t = _learning_workers.get(job_id)
        if t and t.is_alive():
            return
        t = threading.Thread(target=_learning_worker, args=(job_id,), daemon=True, name=f"zar-learning-{job_id[:8]}")
        _learning_workers[job_id] = t
        t.start()

def _learning_worker(job_id):
    try:
        while True:
            job = get_job(job_id)
            if not job or job.get("status") in ("completed", "error", "cancelled", "paused"):
                return
            result = advance_learning(job_id)
            if not result or result.get("status") in ("completed", "error", "cancelled", "paused"):
                return
            time.sleep(0.4)
    finally:
        with _learning_workers_lock:
            _learning_workers.pop(job_id, None)

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

        # Calculate live timing before the first persisted status update.
        # v30.10.4 referenced these values before assigning them, which made
        # every resume fail immediately with UnboundLocalError.
        elapsed_now = round(max(0, time.time() - started), 1)
        avg_per_query = elapsed_now / max(1, idx) if idx else 0
        dynamic_estimate = int(min(MAX_LEARNING_SECONDS, max(60, estimate if idx == 0 else
                                   elapsed_now + max(0, len(qs) - idx) * max(8, avg_per_query))))
        _set_job(job_id,
                 status="researching", phase="Investigando fuentes",
                 message=f"Investigando consulta {min(idx+1, len(qs))}/{len(qs)}…",
                 started_at=started, queries=qs, queries_total=len(qs),
                 query_index=idx, heartbeat_at=time.time(),
                 elapsed_seconds=elapsed_now, estimated_seconds=dynamic_estimate)

        if _cancel_requested(job_id):
            return get_job(job_id)

        research = list(job.get("research") or [])
        sources = list(job.get("sources") or [])

        # Never let the research phase consume more than one hour. If the
        # budget is reached, synthesize everything already collected.
        if elapsed_now >= MAX_LEARNING_SECONDS and idx < len(qs):
            _set_job(job_id, status="synthesizing", progress=max(70, min(82, 8 + int(idx / max(1, len(qs)) * 60))),
                     phase="Sintetizando conocimiento",
                     message=f"Límite de 60 minutos alcanzado; sintetizando {len(sources)} fuentes recopiladas.",
                     heartbeat_at=time.time(), elapsed_seconds=elapsed_now, estimated_seconds=MAX_LEARNING_SECONDS)
            job = _load().get("jobs", {}).get(job_id) or job

        # Process two independent research queries concurrently. This is the
        # main speed improvement: the first pass no longer waits for seven
        # network calls one after another. Each query still has its own
        # fallback cascade and legal/public-source constraints.
        if idx < len(qs) and elapsed_now < MAX_LEARNING_SECONDS:
            batch_indices = list(range(idx, min(idx + 2, len(qs))))
            _set_job(job_id,
                     status="researching", phase="Investigando fuentes",
                     message=f"Investigando consultas {batch_indices[0]+1}-{batch_indices[-1]+1}/{len(qs)} en paralelo…",
                     heartbeat_at=time.time(), elapsed_seconds=round(time.time()-started, 1))
            batch_results = {}
            with ThreadPoolExecutor(max_workers=len(batch_indices)) as pool:
                futures = {pool.submit(_search_one, qs[i]): i for i in batch_indices}
                for future in as_completed(futures):
                    qi = futures[future]
                    try:
                        batch_results[qi] = future.result()
                    except Exception as exc:
                        batch_results[qi] = {"query": qs[qi], "ok": False, "sources": [], "text": "", "attempts": 0, "fallback_used": True, "error": str(exc)}
                    _set_job(job_id, heartbeat_at=time.time(), message=f"Consulta {qi+1}/{len(qs)} procesada; consolidando resultados…")

            for qi in batch_indices:
                item = batch_results.get(qi) or {"query": qs[qi], "ok": False, "sources": [], "text": "", "attempts": 0, "fallback_used": True, "error": "Sin resultado utilizable."}
                research.append(item)
                sources.extend(item.get("sources") or [])

            clean_sources=[]; seen=set()
            for source in sources:
                u=source.get("url")
                if u and u not in seen:
                    seen.add(u); clean_sources.append(source)
            idx = batch_indices[-1] + 1
            progress = 8 + int(idx / max(1, len(qs)) * 60)
            ok_count = sum(1 for qi in batch_indices if (batch_results.get(qi) or {}).get("ok"))
            msg = f"{len(batch_indices)} consultas completadas · {ok_count} con resultados útiles"
            if ok_count < len(batch_indices):
                msg += " · las vías fallidas se han sustituido por alternativas"
            elapsed_now = round(time.time() - started, 1)
            avg_per_query = elapsed_now / max(1, idx)
            dynamic_estimate = int(min(MAX_LEARNING_SECONDS, max(60, elapsed_now + max(0, len(qs) - idx) * max(6, avg_per_query))))
            _set_job(job_id,
                     status="researching" if idx < len(qs) else "synthesizing",
                     progress=progress if idx < len(qs) else 70,
                     phase="Investigando fuentes" if idx < len(qs) else "Sintetizando conocimiento",
                     message=msg,
                     query_index=idx, queries_done=idx, queries_total=len(qs),
                     research=research, sources=clean_sources,
                     source_count=len(clean_sources), heartbeat_at=time.time(),
                     elapsed_seconds=elapsed_now, estimated_seconds=dynamic_estimate)
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
                "estimated_seconds":min(MAX_LEARNING_SECONDS, max(60, int(time.time()-started))),"updated_at":time.time()
            }); _save(d)
            return get_job(job_id)
        return get_job(job_id)
    except Exception as exc:
        if not _cancel_requested(job_id):
            current = (_load().get("jobs", {}).get(job_id) or {})
            started0 = float(current.get("started_at") or time.time())
            # Never report 100% for a failed learning session. Keep the real
            # persisted progress so the user can retry from the last checkpoint.
            idx0 = int(current.get("query_index") or 0)
            total0 = max(1, int(current.get("queries_total") or len(current.get("queries") or []) or 1))
            progress0 = int(current.get("progress") or (8 + int(idx0 / total0 * 60)))
            progress0 = max(5, min(99, progress0))
            _set_job(job_id, status="error", progress=progress0, phase="Error",
                     message=str(exc)[:1200], query_index=idx0,
                     queries_done=idx0, queries_total=total0,
                     heartbeat_at=time.time(),
                     elapsed_seconds=round(max(0, time.time()-started0),1))
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
    estimate=min(MAX_LEARNING_SECONDS, max(60, len(qs)*14+30))
    _set_job(job_id,
             status="queued", progress=5, phase="En cola",
             message="Aprendizaje creado. ZAR iniciará la primera consulta al actualizar su estado.",
             topic=topic, goal=str(goal or "").strip(), references=references,
             queries=qs, query_index=0, queries_total=len(qs), queries_done=0,
             source_count=0, research=[], sources=[], created_at=now, updated_at=now,
             started_at=now, session_started_at=now, estimated_seconds=estimate, heartbeat_at=now,
             learning_id=uuid.uuid4().hex)
    # v30.10.11: start the durable in-process worker immediately. State is
    # persisted after every bounded step, and the API can restart the worker
    # after a Railway process restart when the user next opens ZAR.
    _ensure_learning_worker(job_id)
    return get_job(job_id)


def resume_learning(job_id):
    job=get_job(job_id)
    if not job: raise ValueError("Aprendizaje no encontrado.")
    if job.get("status")=="completed": return job
    topic=str(job.get("topic") or "").strip()
    if not topic: raise ValueError("El aprendizaje no tiene tema recuperable.")
    qs = list(job.get("queries") or _query_plan(topic, str(job.get("goal") or "").strip(), list(job.get("references") or [])))
    idx = int(job.get("query_index") or 0)
    idx = max(0, min(idx, len(qs)))
    if idx >= len(qs):
        resume_progress = 70
    else:
        resume_progress = max(5, 8 + int(idx / max(1, len(qs)) * 60))
    now=time.time()
    _set_job(job_id, status="queued", progress=resume_progress, phase="Reanudando",
             message="Aprendizaje reanudado. Continuaré desde la última consulta guardada con un nuevo presupuesto de hasta 60 minutos.",
             started_at=now, session_started_at=now, heartbeat_at=now, cancel_requested=False, queries=qs,
             queries_total=len(qs), query_index=idx, queries_done=idx, estimated_seconds=min(MAX_LEARNING_SECONDS, max(60, int((len(qs)-idx)*14+30))))
    _ensure_learning_worker(job_id)
    return get_job(job_id)

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
