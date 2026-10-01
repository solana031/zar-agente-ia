# ZAR 32.0.4 — Workspace Pro + cierre seguro de prueba Paper huérfana

## Stonks
- Añade detección visible de una única prueba TEST_LIFECYCLE perteneciente a un owner anterior.
- En Carteras & API aparece «Cerrar prueba Paper pendiente» únicamente cuando Alpaca confirma exactamente una posición, cero órdenes abiertas y el ledger anterior demuestra que esa posición procede de TEST_LIFECYCLE.
- El cierre requiere confirmación explícita y envía exclusivamente una orden SELL a Alpaca Paper por la cantidad exacta verificada.
- No habilita Live, no crea venta en corto y no toca otras posiciones.

## Workspace Pro
- Google Sheets deja de limitarse a volcar valores: cualquier escritura recibe formato base profesional, autoajuste de columnas, cabeceras y filas de resumen destacadas.
- Nueva herramienta `sheets_add_professional_table` para añadir subtables profesionales a hojas existentes.
- Nueva herramienta `sheets_build_workbook` para crear libros completos con varias pestañas, títulos, subtítulos, tablas y resúmenes.
- Nueva herramienta `docs_build_report` para informes de Google Docs con jerarquía de título, subtítulo y secciones.
- Nueva herramienta `slides_build_deck` para presentaciones Google Slides con portada y diapositivas estructuradas.
- El router Workspace expone estas herramientas y el prompt de ZAR las prioriza para entregables reales; las herramientas simples quedan para archivos deliberadamente vacíos.

## Seguridad
- Todas las mutaciones de Google Workspace siguen pasando por confirmación explícita.
- LIVE_TRADING_ENABLED sigue bloqueado.
