# ZAR v32.1.5 — Evidence-first Workspace

## Objetivo
Convierte Workspace de un generador de tablas a un sistema operativo basado en evidencia: cada archivo subido se conserva, se intenta analizar automáticamente y sus datos estructurados pueden alimentar controles de negocio sin mezclar unidades ni inventar valores.

## Cambios
- Análisis automático tras cada subida, con `analysis_status` y `analysis_error` persistentes.
- Extracción estructurada para `cash_closure` y `shift_records`.
- Nuevas categorías `cierres_caja` y `turnos`.
- Tool confirmable `sheets_sync_business_control` para reconstruir un Sheets desde archivos analizados y datos manuales confirmados.
- Calendario diario completo del mes para turnos.
- Cierres diarios con efectivo, tarjeta, total, TPV/datáfono, descuadre, operaciones y observaciones.
- Evidencia visual tokenizada: imágenes subidas pueden mostrarse dentro de Google Sheets mediante `IMAGE()` sin exponer el fichero por ID simple.
- Formato de columnas corregido: horas/duración tienen prioridad sobre palabras genéricas como `total`, evitando formatos de moneda incorrectos.
- Las pestañas originales se conservan; solo se reconstruyen las cuatro pestañas gestionadas por el sincronizador.

## Seguridad e integridad
- Una foto/documento nunca se elimina si el análisis falla.
- Si Gemini falla, el archivo permanece guardado y queda marcado con error de análisis.
- No se inventan días, importes o turnos ausentes: quedan como `Sin datos`/vacío.
- La sincronización con Sheets sigue requiriendo la confirmación de Workspace existente.
