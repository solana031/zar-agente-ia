# ZAR v32.1.7 — Attachment Pipeline & Workspace Analyze-First

## Cambios
- Los archivos empiezan a subirse inmediatamente al seleccionarlos, antes de enviar el mensaje.
- El compositor muestra estado visible: 0–100 %, bytes, guardado/indexado, analizando y listo/error.
- Los adjuntos permanecen vinculados visualmente al mensaje pendiente hasta pulsar Enviar.
- Si se pulsa Enviar durante una subida/análisis, ZAR espera a que termine el pipeline.
- Workspace respeta el orden `analizar → mostrar extracción → confirmar → modificar` y no intenta preparar Sheets antes de tiempo.
- Se conservan reintentos/fallback visual, biblioteca persistente y mejoras de contactos de 32.1.6.
- Stonks no se modifica.
