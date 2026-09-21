# ZAR v27.32 — Google offline backup + Tasks

## Backup local independiente de Google

Tras una autorización válida, Zar conserva una copia local en `ZAR_DATA_DIR/backups/google` y la indexa en la memoria SQLite. La copia incluye, según permisos y APIs disponibles:

- Gmail: todos los mensajes accesibles, incluidos spam/papelera, etiquetas, borradores y adjuntos pequeños.
- Contactos de Google People.
- Todos los calendarios y sus eventos accesibles.
- Google Tasks: listas y tareas, incluidas completadas/ocultas.
- Google Drive: metadatos y contenido/exportaciones hasta el límite configurado.
- Texto extraíble de documentos de Drive y adjuntos de Gmail se indexa para poder localizarlo sin conexión a Google.

## Actualización automática

Al abrir Zar, si la última copia tiene más de 24 horas, se inicia otra en segundo plano. También existe un botón en Centro de control y `POST /api/google/backup/start`.

Variables opcionales:
- `ZAR_GOOGLE_BACKUP_MAX_FILE_MB` — 25 MB por defecto para archivos de Drive.
- `ZAR_GOOGLE_BACKUP_MAX_ATTACHMENT_MB` — 25 MB por defecto para adjuntos de Gmail.
- `ZAR_GOOGLE_BACKUP_INDEX_MAX_MESSAGES` — 50.000 mensajes por defecto en el índice local.

## Persistencia

Railway debe tener un Volume persistente montado en `/data` (o el valor de `ZAR_DATA_DIR`). Sin un almacenamiento persistente, una nueva instancia puede perder los snapshots.

## Nuevo permiso

Se añade `https://www.googleapis.com/auth/tasks.readonly`. Hay que añadir ese alcance en Google Auth Platform → Acceso a los datos y hacer una reautorización una sola vez para que Zar pueda copiar Google Tasks.
