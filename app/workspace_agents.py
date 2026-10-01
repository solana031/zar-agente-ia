"""Zero-token specialist planner and quality contract for ZAR Workspace.

The specialists are logical sub-agents: they do not create extra LLM calls by
themselves. They constrain tool choice, define deliverable standards and make
Workspace outputs consistently professional without multiplying token/API cost.
"""
from __future__ import annotations
import re

AGENTS = [
    {'id':'workspace_supervisor','name':'Workspace Supervisor','role':'Planifica el entregable, coordina especialistas, minimiza acciones y verifica que el resultado cubra la petición.'},
    {'id':'workspace_research','name':'Research Agent','role':'Busca y contrasta información pública actual cuando faltan datos externos; separa hechos internos de fuentes externas.'},
    {'id':'workspace_visual_research','name':'Visual Research Agent','role':'Busca imágenes públicas/reutilizables y conserva fuente/licencia para Docs/Slides.'},
    {'id':'workspace_data','name':'Data Analyst','role':'Normaliza datos, detecta métricas, calcula totales, inconsistencias y propone tablas/KPIs/gráficos útiles.'},
    {'id':'workspace_sheets','name':'Sheets Designer','role':'Diseña libros, pestañas, tablas, formatos, filtros, dashboards y gráficos legibles.'},
    {'id':'workspace_docs','name':'Docs Designer','role':'Estructura informes con resumen ejecutivo, jerarquía, tablas conceptuales y redacción lista para compartir.'},
    {'id':'workspace_slides','name':'Slides Designer','role':'Convierte contenido en narrativa visual con una idea por diapositiva, jerarquía, imágenes y poco texto.'},
    {'id':'workspace_qa','name':'Quality Agent','role':'Comprueba integridad, legibilidad, fuentes, consistencia, ausencia de pérdidas y que no se afirmen acciones no ejecutadas.'},
]

def plan(message):
    t=(message or '').lower()
    steps=['workspace_supervisor']
    if re.search(r'\b(busca|investiga|internet|web|actual|fuente|mercado|competencia)\b',t): steps.append('workspace_research')
    if re.search(r'\b(imagen|foto|visual|icono|mapa|referencia visual)\b',t): steps.append('workspace_visual_research')
    if re.search(r'\b(datos|tabla|gráfico|grafico|kpi|métrica|metrica|total|horas|caja|ventas|resumen|balance|inventario)\b',t): steps.append('workspace_data')
    if re.search(r'\b(sheet|sheets|excel|hoja de cálculo|hoja de calculo)\b',t): steps.append('workspace_sheets')
    if re.search(r'\b(doc|docs|documento|informe|acta|propuesta)\b',t): steps.append('workspace_docs')
    if re.search(r'\b(slides|presentación|presentacion|diapositiva)\b',t): steps.append('workspace_slides')
    steps.append('workspace_qa')
    seen=[]
    for x in steps:
        if x not in seen: seen.append(x)
    by={a['id']:a for a in AGENTS}
    return {'agents':[by[x] for x in seen if x in by], 'ids':seen, 'zero_token_router':True}

def quality_contract(message):
    t=(message or '').lower()
    rules=[
        'Conservar todos los datos existentes salvo petición explícita de borrado.',
        'No inventar cifras, fechas, fuentes, enlaces ni resultados de herramientas.',
        'Una sola confirmación por entregable siempre que una herramienta profesional pueda ejecutar el trabajo completo.',
        'Después de ejecutar, devolver enlace/ID real y resumir exactamente qué se creó o modificó.',
    ]
    if re.search(r'\b(sheet|sheets|excel|hoja de cálculo|hoja de calculo)\b',t):
        rules += [
            'Sheets: usar pestañas con propósito claro; separar datos base de resumen cuando el caso lo justifique.',
            'Sheets: títulos, cabeceras, filtros, filas congeladas, formatos de fecha/moneda/porcentaje/horas y anchos legibles.',
            'Sheets: KPIs y gráficos solo si responden a una pregunta de gestión; nunca gráficos decorativos.',
            'Sheets: distinguir total, pagado, pendiente, saldo y diferencias cuando existan esos conceptos.',
        ]
    if re.search(r'\b(doc|docs|documento|informe|acta|propuesta)\b',t):
        rules += [
            'Docs: título + resumen ejecutivo + secciones jerarquizadas + conclusiones/pendientes cuando proceda.',
            'Docs: evitar párrafos gigantes; preferir bloques breves y datos cuantitativos claramente separados.',
        ]
    if re.search(r'\b(slides|presentación|presentacion|diapositiva)\b',t):
        rules += [
            'Slides: una idea principal por diapositiva, máximo aproximado de 5-6 bullets y texto breve.',
            'Slides: usar imágenes solo con procedencia conocida; incluir nota de fuente cuando corresponda.',
        ]
    return rules

def prompt(message):
    p=plan(message)
    agents=' → '.join(a['name'] for a in p['agents'])
    rules=' | '.join(quality_contract(message))
    return agents + (' | CONTRATO QA: '+rules if rules else '')
