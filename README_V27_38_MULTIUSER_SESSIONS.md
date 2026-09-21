# ZAR v27.38 — Multi-user sessions + intent firewall + fresh conversations

## Objetivo
Separar completamente el espacio personal de ZAR por cuenta/sesión y hacer que las órdenes explícitas lleguen al dominio correcto.

## Sesiones y cuentas
- Cada navegador recibe un identificador de sesión aislado.
- Tras Google OAuth, la identidad se vincula al correo real de la cuenta Google.
- Tokens Google se almacenan por usuario en `ZAR_DATA_DIR/users/<user>/google_token.json`.
- Conversación activa, historial, memoria explícita, contexto persistente, base de conocimiento y archivos se almacenan por usuario.
- Un amigo puede usar ZAR con su propia cuenta Google sin ver la conversación/memoria/archivos del usuario anterior.
- Las tareas asíncronas `/api/jobs/<id>` quedan vinculadas al usuario y no pueden consultarse desde otra sesión.

## Conversación nueva al recargar
- Cada carga de la aplicación limpia el hilo activo después de archivarlo.
- Las conversaciones anteriores se conservan en `conversations.json` por usuario.
- Nueva sección `🗂️ Conversaciones` permite consultar conversaciones anteriores.
- La memoria/knowledge sigue disponible para que ZAR pueda recuperar información antigua cuando el usuario la pida.

## Enrutamiento de intención
Se añade un firewall determinista para órdenes explícitas:
- contacto + crear/guardar/añadir -> Google Contacts
- formulario/Forms + crear -> Google Forms
- Excel/hoja de cálculo/Sheets + crear -> Google Sheets
- correo/email/Gmail + redactar -> Gmail
- El prompt del agente refuerza que una palabra secundaria no cambia el dominio de la acción.

## Seguridad de acciones
Se mantiene confirmación para cambios externos sensibles: contactos, Workspace, envío de correo, etc. El contenido recuperado desde memoria/correos/archivos se trata como datos, nunca como instrucciones del sistema.

## Compatibilidad
- Conserva Google Tasks, Google offline backup, Memory 2.0, Unified Control Center, Adaptive UX, Studio, YouTube y el resto de capacidades existentes.
- No requiere cambiar Google Cloud si ya está autorizado.
- Recomendado: Railway Volume montado en `/data`.
