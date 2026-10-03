# ZAR v32.1.15 — Confirmation Status Fallback

## Fix principal
- Añade `/api/confirmation-status` como fuente persistente de verdad para confirmaciones pendientes.
- Si un job de chat termina sin `confirmation` embebida, el frontend consulta automáticamente ese endpoint y renderiza `Confirmar / Cancelar` en la misma respuesta.
- Incluye reintentos cortos para cubrir carreras entre el worker asíncrono y la persistencia del estado.
- Mantiene el flujo estructurado de confirmación; no obliga a escribir “Sí”.

## Conservado
- Arreglo idempotente de banding en Google Sheets.
- Sin cambios en ZAR Stonks.
