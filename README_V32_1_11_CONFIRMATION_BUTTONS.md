# ZAR v32.1.11 — Confirmation Buttons

- Añade controles visibles **Confirmar** / **Cancelar** a las respuestas que requieren autorización.
- Las decisiones de los botones usan señales internas estructuradas, no dependen de interpretar la palabra «Sí».
- Amplía la detección de confirmaciones naturales a frases como «¿Quieres registrar estos datos…?».
- Mantiene recuperación del último pedido Workspace si el modelo formuló la confirmación antes de persistir el payload.
- Añade soporte del mismo patrón de confirmación para Workspace, Gmail, Contactos y Calendar.
- Los botones se deshabilitan durante la ejecución para evitar doble confirmación.
- No modifica ZAR Stonks.
