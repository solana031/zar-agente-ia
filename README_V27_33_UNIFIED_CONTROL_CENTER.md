# ZAR v27.33 — Unified Control Center

Esta versión reorganiza el Centro de control para que el estado de ZAR sea visible de un vistazo.

## Incluye
- Panel unificado de salud de ZAR.
- Cuenta Google conectada (cuando Gmail permite obtener el perfil).
- Estado individual de Gmail, Calendar, Contacts, Tasks, Drive, Docs, Sheets, Slides y Forms.
- Detección de permisos OAuth pendientes y estado "Requiere autorización".
- Estado de la copia local de Google y métricas principales.
- Botón para iniciar una copia manual desde el Centro de control.
- Resumen de memoria: fuentes y fragmentos indexados.
- Motor/modelo de IA visible.
- Panel específico de "Conexiones" para inspeccionar autorización y reautorizar Google.
- Mantiene las funciones existentes de Workspace, Maps, Multimedia, Memoria, Archivos, Voz e Internet.

## Importante
La clasificación de cada servicio refleja la autorización OAuth disponible en el token. No significa que se haya hecho una lectura completa de todos los datos en cada visita al panel.

La copia Google sigue siendo local y persistente si `ZAR_DATA_DIR` apunta a un almacenamiento persistente (en Railway, normalmente `/data`).
