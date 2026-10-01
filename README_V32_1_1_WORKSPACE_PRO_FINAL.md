# ZAR 32.1.1 — Workspace Pro Final

## Objetivo
Cerrar la capa Workspace profesional sin modificar la lógica operativa de ZAR Stonks 32.1.0.

## Mejoras
- Workspace multiagente visible en Orquestación: Supervisor, Research, Visual Research, Data Analyst, Sheets Designer, Docs Designer, Slides Designer y Quality Agent.
- Contrato QA determinista por tipo de entregable, sin llamadas LLM adicionales.
- `sheets_upgrade_workbook` incluido explícitamente en la política de acciones sensibles.
- Sheets profesional reforzado: filtros, fila de cabeceras congelada, bandas visuales, autoajuste, formatos inferidos de moneda/fecha/hora/porcentaje/horas y bloque KPI/resumen.
- Mantiene datos existentes: las capas profesionales se crean/actualizan sin borrar pestañas originales.
- Una sola acción confirmable para reorganizaciones completas de un Sheets existente.
- Reglas de Docs: resumen ejecutivo, secciones jerarquizadas y legibilidad.
- Reglas de Slides: una idea por diapositiva, densidad controlada, imágenes con procedencia/licencia y fuentes visibles cuando corresponda.
- Research/Visual Research se activan solo cuando la petición necesita información externa o imágenes.

## Seguridad
- No se ha modificado LIVE de Stonks.
- Stonks 32.1.0 multiactivo se conserva.
- Las escrituras de Workspace requieren confirmación explícita.
