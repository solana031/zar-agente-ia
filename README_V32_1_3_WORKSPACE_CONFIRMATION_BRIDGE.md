# ZAR v32.1.3 — Workspace Confirmation Bridge

Hotfix sobre 32.1.2 para cerrar definitivamente el flujo de confirmación de Google Workspace.

## Correcciones
- Si el modelo redacta un plan de Workspace y pide confirmación sin haber emitido `WORKSPACE_ACTION`, ZAR realiza una segunda pasada interna obligatoria para preparar la acción estructurada antes de mostrar la confirmación.
- La acción queda persistida en contexto durable y sesión del navegador antes de que el usuario vea «¿Confirmas?». 
- Si llega un «Sí» con una tarea Workspace en `awaiting_confirmation` pero el payload se perdió, ZAR recupera la última orden Workspace del historial, reconstruye la acción y la ejecuta únicamente después de esa confirmación explícita.
- No se modifica ningún archivo externo si no se puede reconstruir la acción de forma segura.

## Seguridad
- Se mantiene una única confirmación explícita para escrituras en Workspace.
- No se modifica Stonks, Risk, Paper, Shadow ni LIVE.
