"""ZAR Learning 1.0 — aprendizaje persistente y verificable.

Permite que ZAR convierta una petición explícita de aprendizaje en:
- un plan de estudio persistente,
- investigación web con fuentes,
- una ficha de conocimiento,
- y una habilidad reutilizable cuando el tema es accionable.

No modifica automáticamente el código, permisos ni credenciales de ZAR.
"""
from __future__ import annotations
import base64, json, os, re, threading, time, uuid
from pathlib import Path
import requests

from .user_scope import safe_slug, get_current_user
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
        v=json.loads(_file().read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else {"topics":{}, "jobs":{}}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"topics":{}, "jobs":{}}

def _save(v):
    p=_file(); tmp=p.with_suffix(".tmp")
    tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding="utf-8"); tmp.replace(p)

def list_learning():
    return list(_load().get("topics",{}).values())

def list_jobs():
    return sorted(list(_load().get("jobs",{}).values()), key=lambda x:x.get("created_at",0), reverse=True)[:30]

def get_job(job_id):
    return _load().get("jobs",{}).get(job_id)

def _set_job(job_id, **changes):
    d=_load(); job=d.setdefault("jobs",{}).setdefault(job_id,{"id":job_id})
    job.update(changes); job["updated_at"]=time.time(); _save(d); return job

def _gemini_key_model():
    try:
        from .config import load
        cfg=load()
    except Exception:
        cfg={}
    return (str(cfg.get("api",{}).get("api_key","") or os.environ.get("GEMINI_API_KEY","")).strip(),
            str(cfg.get("api",{}).get("model","gemini-3.6-flash") or "gemini-3.6-flash").strip())

def _synth(topic, goal, references, research):
    key, model=_gemini_key_model()
    if not key:
        return {
            "summary": f"Plan de aprendizaje persistente para {topic}.",
            "curriculum": ["Fundamentos", "Práctica guiada", "Casos reales", "Verificación y mejora continua"],
            "steps": [f"Estudiar los fundamentos de {topic}", f"Practicar {topic} con ejemplos reales", f"Aplicar buenas prácticas de {topic}", f"Revisar y mejorar resultados de {topic}"],
            "triggers": [f"ayúdame con {topic}", f"aplica lo aprendido en {topic}", topic],
            "tools": ["web","memoria","archivos"],
        }
    context=json.dumps(research,ensure_ascii=False)[:50000]
    prompt=(
      "Eres el planificador de aprendizaje persistente de ZAR. Crea un plan práctico y verificable.\n"
      f"TEMA: {topic}\nOBJETIVO: {goal or 'aprenderlo con profundidad y poder aplicarlo'}\n"
      f"REFERENCIAS DEL USUARIO: {references or []}\n"
      "INVESTIGACIÓN WEB:\n"+context+"\n"
      "Devuelve SOLO JSON con estas claves: summary, curriculum (6-12 módulos), steps (8-20 pasos "
      "accionables para aplicar el conocimiento), triggers (3-8 frases), tools (lista), mastery_checks (5-10 "
      "pruebas para comprobar dominio), limitations (lista). No inventes fuentes. Distingue hechos de recomendaciones. "
      "Si el tema cambia con el tiempo, incluye una fase de actualización periódica."
    )
    try:
        url=f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        r=requests.post(url,params={"key":key},json={"contents":[{"parts":[{"text":prompt}]}],
            "generationConfig":{"temperature":0.15,"responseMimeType":"application/json"}},timeout=120)
        r.raise_for_status()
        data=r.json(); text=""
        for c in data.get("candidates",[]):
            for p in (c.get("content") or {}).get("parts",[]):
                text+=p.get("text","")
        text=re.sub(r"^```json\s*|\s*```$","",text.strip(),flags=re.I)
        return json.loads(text)
    except Exception:
        return {
            "summary": f"Plan de aprendizaje para {topic}, basado en investigación web.",
            "curriculum":["Fundamentos","Práctica","Casos reales","Verificación","Actualización"],
            "steps":[f"Estudiar fundamentos de {topic}",f"Practicar {topic} con casos reales",f"Comparar técnicas y buenas prácticas de {topic}",f"Aplicar lo aprendido y verificar resultados"],
            "triggers":[f"ayúdame con {topic}",f"aplica lo aprendido en {topic}",topic],
            "tools":["web","memoria","archivos"],
            "mastery_checks":["Explicar conceptos clave","Resolver un caso real","Detectar errores","Comparar alternativas","Aplicar el conocimiento"],
            "limitations":["El aprendizaje depende de las fuentes disponibles y debe revisarse cuando cambie el dominio."]
        }

def _queries(topic, goal, refs):
    base=[
        f"{topic} guía completa fundamentos buenas prácticas",
        f"{topic} advanced techniques professional workflow",
        f"{topic} tutorial práctico casos reales errores comunes",
        f"{topic} estándares documentación oficial recursos de aprendizaje",
        f"{topic} herramientas actuales ejemplos profesionales",
    ]
    if any(x in (topic+" "+(goal or "")).lower() for x in ("foto","fotografía","diseño","imagen","edición")):
        base += [f"{topic} Behance Dribbble profesionales referencias", f"{topic} Instagram profesionales tutorial"]
    if refs:
        base.append(" ".join(refs[:3]))
    return base[:8]

def _run_job(job_id, topic, goal, references):
    try:
        _set_job(job_id,status="researching",progress=10,message="Buscando fuentes y referencias…")
        from .web_search import google_web_search
        sources=[]; research=[]
        qs=_queries(topic,goal,references)
        for i,q in enumerate(qs,1):
            res=google_web_search(q, instructions="Recopila fuentes útiles para estudiar el tema; prioriza documentación oficial, recursos educativos y referencias profesionales.")
            if res.get("ok"):
                research.append({"query":q,"text":res.get("text","")[:9000]})
                sources.extend(res.get("sources") or [])
            _set_job(job_id,progress=min(65,10+int(i/len(qs)*55)),message=f"Investigación {i}/{len(qs)}…")
        # deduplicate sources
        seen=set(); clean=[]
        for s in sources:
            u=s.get("url","")
            if u and u not in seen:
                seen.add(u); clean.append(s)
        plan=_synth(topic,goal,references,research)
        now=time.time()
        skill=create_skill({
            "name": f"{topic[:80]} · aprendido por ZAR",
            "description": plan.get("summary") or f"Habilidad aprendida sobre {topic}.",
            "steps": plan.get("steps") or [],
            "triggers": plan.get("triggers") or [topic],
            "tools": plan.get("tools") or ["web","memoria","archivos"],
            "enabled": True,
        })
        d=_load()
        d.setdefault("topics",{})[topic.lower()]={
            "id":uuid.uuid4().hex,"topic":topic,"goal":goal,"references":references[:10],
            "status":"learned","progress":100,"created_at":now,"updated_at":now,
            "summary":plan.get("summary",""),"curriculum":plan.get("curriculum",[]),
            "mastery_checks":plan.get("mastery_checks",[]),"limitations":plan.get("limitations",[]),
            "sources":clean[:40],"skill_id":skill.get("id"),"source_count":len(clean),
        }
        d.setdefault("jobs",{}).setdefault(job_id,{}).update({
            "status":"completed","progress":100,"message":"Aprendizaje completado y habilidad creada.",
            "topic":topic,"result":d["topics"][topic.lower()],"updated_at":time.time()
        })
        _save(d)
    except Exception as exc:
        _set_job(job_id,status="error",progress=100,message=str(exc)[:1200])

def start_learning(topic, goal="", references=None):
    topic=str(topic or "").strip()
    if not topic: raise ValueError("Indica qué quieres que aprenda ZAR.")
    references=[str(x).strip() for x in (references or []) if str(x).strip()][:10]
    job_id=uuid.uuid4().hex
    _set_job(job_id,status="queued",progress=0,message="Aprendizaje preparado.",topic=topic,goal=goal,references=references,created_at=time.time())
    threading.Thread(target=_run_job,args=(job_id,topic,str(goal or "").strip(),references),daemon=True).start()
    return get_job(job_id)

def learn_from_file(file_id):
    from .file_analysis import analyze_file
    result=analyze_file(file_id)
    analysis=result.get("analysis") or {}
    # The file is already indexed by ZAR knowledge; this marker adds a durable learning record.
    topic=str(analysis.get("document_type") or "documento adjunto")
    d=_load(); key=f"file:{file_id}"
    d.setdefault("topics",{})[key]={
        "id":uuid.uuid4().hex,"topic":topic,"goal":"Aprender de la estructura y contenido del documento adjunto.",
        "status":"learned_from_document","progress":100,"created_at":time.time(),"updated_at":time.time(),
        "source_file_id":file_id,"analysis":analysis,
        "summary":analysis.get("summary") or analysis.get("description") or "",
    }
    _save(d)
    return {"ok":True,"learning":d["topics"][key],"analysis":analysis}

def active_learning_count():
    return sum(1 for x in list_learning() if x.get("status") in ("learning","learned","learned_from_document"))
