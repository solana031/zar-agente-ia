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
        {"id":"workspace_supervisor","name":"Workspace Supervisor","icon":"✧","domain":"productivity","role":"Coordina entregables Workspace y controla calidad/confirmaciones","status":"ready"},
        {"id":"workspace_research","name":"Workspace Research","icon":"⌕","domain":"research","role":"Busca y contrasta información pública necesaria para el entregable","status":"ready"},
        {"id":"workspace_visual","name":"Visual Research","icon":"▧","domain":"research","role":"Localiza imágenes reutilizables con fuente/licencia para Docs y Slides","status":"ready"},
        {"id":"workspace_data","name":"Data Analyst","icon":"▦","domain":"productivity","role":"Normaliza datos, calcula KPIs y decide tablas/gráficos útiles","status":"ready"},
        {"id":"workspace_sheets","name":"Sheets Designer","icon":"▤","domain":"productivity","role":"Diseña libros, tablas, dashboards, formatos y gráficos","status":"ready"},
        {"id":"workspace_docs","name":"Docs Designer","icon":"▥","domain":"productivity","role":"Maqueta informes, actas y propuestas con jerarquía profesional","status":"ready"},
        {"id":"workspace_slides","name":"Slides Designer","icon":"▰","domain":"productivity","role":"Crea narrativa visual, jerarquía, imágenes y densidad adecuada","status":"ready"},
        {"id":"workspace_qa","name":"Workspace Quality","icon":"✓","domain":"productivity","role":"Valida integridad, legibilidad, fuentes y resultado final","status":"ready"},
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
        ["workspace","workspace_supervisor"],
        ["workspace_supervisor","workspace_research"],["workspace_supervisor","workspace_visual"],
        ["workspace_supervisor","workspace_data"],["workspace_supervisor","workspace_sheets"],
        ["workspace_supervisor","workspace_docs"],["workspace_supervisor","workspace_slides"],
        ["workspace_supervisor","workspace_qa"],["workspace_research","workspace_qa"],
        ["workspace_visual","workspace_qa"],["workspace_data","workspace_qa"],
        ["workspace_sheets","workspace_qa"],["workspace_docs","workspace_qa"],["workspace_slides","workspace_qa"],
    ]
    return {"updated_at":_now(),"agents":agents,"edges":edges,"router_token_cost":0}
