"""Global ZAR sub-agent registry and observability helpers.

This module is intentionally lightweight and deterministic. It does not call an LLM.
It exposes a shared registry so the UI can visualise ZAR specialists and their links.
"""
from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat()


def describe_general_agents():
    agents = [
        {"id":"zar_supervisor","name":"ZAR Supervisor","icon":"✦","domain":"core","role":"Clasifica intención, coordina especialistas y consolida resultados","status":"ready"},
        {"id":"workspace","name":"Workspace Agent","icon":"☁","domain":"productivity","role":"Gmail, Calendar, Drive, Docs, Sheets, Slides, Forms y Tasks","status":"ready"},
        {"id":"memory","name":"Memory Agent","icon":"◉","domain":"memory","role":"Recuperación semántica, contexto activo y memoria persistente","status":"ready"},
        {"id":"research","name":"Research Agent","icon":"⌕","domain":"research","role":"Investigación web, síntesis y fuentes públicas","status":"ready"},
        {"id":"files","name":"Files Agent","icon":"▣","domain":"files","role":"Biblioteca, búsqueda, metadatos y recuperación de archivos","status":"ready"},
        {"id":"studio","name":"Studio Agent","icon":"▶","domain":"media","role":"Vídeo, imagen, audio y proyectos multimedia","status":"ready"},
        {"id":"voice","name":"Voice Agent","icon":"◌","domain":"voice","role":"Entrada de voz, transcripción y salida hablada","status":"ready"},
        {"id":"stonks_supervisor","name":"Stonks Supervisor","icon":"↗","domain":"finance","role":"Coordina especialistas Paper de ZAR Stonks","status":"ready"},
    ]
    edges = [
        ["zar_supervisor","workspace"],["zar_supervisor","memory"],["zar_supervisor","research"],
        ["zar_supervisor","files"],["zar_supervisor","studio"],["zar_supervisor","voice"],
        ["zar_supervisor","stonks_supervisor"],["research","memory"],["files","memory"],
    ]
    return {"updated_at":_now(),"agents":agents,"edges":edges,"router_token_cost":0}
