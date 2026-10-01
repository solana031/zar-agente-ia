"""Zero-token specialist planner for ZAR Workspace.

These specialists are logical sub-agents: they do not create extra LLM calls by
 themselves. They constrain tool choice and define quality gates so Workspace
 work is richer without multiplying token/API cost.
"""
from __future__ import annotations
import re

AGENTS = [
    {'id':'workspace_supervisor','name':'Workspace Supervisor','role':'Planifica el entregable, coordina especialistas y verifica que la acción final cubra la petición.'},
    {'id':'workspace_research','name':'Research Agent','role':'Busca y contrasta información pública cuando faltan datos actuales o externos.'},
    {'id':'workspace_visual_research','name':'Visual Research Agent','role':'Busca imágenes públicas/reutilizables y conserva fuente/licencia para Docs/Slides.'},
    {'id':'workspace_data','name':'Data Analyst','role':'Normaliza datos, detecta métricas, calcula totales y propone tablas/KPIs/gráficos útiles.'},
    {'id':'workspace_sheets','name':'Sheets Designer','role':'Diseña libros, pestañas, tablas, formatos, dashboards y gráficos.'},
    {'id':'workspace_docs','name':'Docs Designer','role':'Estructura informes con jerarquía, tablas y redacción lista para compartir.'},
    {'id':'workspace_slides','name':'Slides Designer','role':'Convierte contenido en narrativa visual, jerarquía, imágenes y poco texto por diapositiva.'},
    {'id':'workspace_qa','name':'Quality Agent','role':'Comprueba integridad de datos, legibilidad, fuentes, consistencia y ausencia de pérdidas antes de ejecutar.'},
]

def plan(message):
    t=(message or '').lower()
    steps=['workspace_supervisor']
    if re.search(r'\b(busca|investiga|internet|web|actual|fuente|mercado|competencia)\b',t): steps.append('workspace_research')
    if re.search(r'\b(imagen|foto|visual|icono|mapa|referencia visual)\b',t): steps.append('workspace_visual_research')
    if re.search(r'\b(datos|tabla|gráfico|grafico|kpi|métrica|metrica|total|horas|caja|ventas|resumen)\b',t): steps.append('workspace_data')
    if re.search(r'\b(sheet|sheets|excel|hoja de cálculo|hoja de calculo)\b',t): steps.append('workspace_sheets')
    if re.search(r'\b(doc|docs|documento|informe|acta|propuesta)\b',t): steps.append('workspace_docs')
    if re.search(r'\b(slides|presentación|presentacion|diapositiva)\b',t): steps.append('workspace_slides')
    steps.append('workspace_qa')
    seen=[]
    for x in steps:
        if x not in seen: seen.append(x)
    by={a['id']:a for a in AGENTS}
    return {'agents':[by[x] for x in seen if x in by], 'ids':seen, 'zero_token_router':True}

def prompt(message):
    p=plan(message)
    return ' → '.join(a['name'] for a in p['agents'])
