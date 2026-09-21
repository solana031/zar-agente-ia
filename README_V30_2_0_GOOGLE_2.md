# ZAR v30.2.0 — Bloque 3 · Google 2.0

Esta versión conserva todo lo validado en v30.1.2 y añade una capa de diagnóstico vivo para Google.

## Novedades
- Estado por servicio de Gmail, Calendar, Contactos, Tasks y Google Workspace.
- Endpoint `/api/google/services/check` para comprobar las APIs con la cuenta actual.
- Separación entre permiso OAuth y estado operativo real.
- Medición de latencia de las comprobaciones cuando la API responde.
- Panel Conexiones con cuenta Google, refresh token, permisos pendientes y verificación en vivo.
- Google Docs, Sheets, Slides y Forms se comprueban profundamente cuando existe al menos un objeto del tipo correspondiente; si no existe, se mantiene el estado de autorización sin marcar un falso error.
- Se conserva la copia local de Google y el aislamiento por usuario.

## Servicios
Gmail · Calendar · Drive · Docs · Sheets · Slides · Forms · Contactos · Tareas.

## Persistencia
No se incluye `data/` en el ZIP de release. La información de usuario permanece en el almacenamiento persistente configurado por ZAR. En Railway debe existir un Volume montado en `/data` para que sobreviva a redeploys.
