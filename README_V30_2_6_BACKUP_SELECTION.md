# ZAR v30.2.6 — Copia Google configurable y progreso real

## Qué cambia
- La copia de seguridad de Google ya no se presenta como una copia de todo el ordenador: trabaja sobre los datos autorizados de Google que ZAR puede consultar.
- Antes de iniciar una copia manual, ZAR abre un selector para elegir exactamente qué conservar.
- Opción **Seleccionar todo** para una copia completa.
- Bloques seleccionables:
  - Gmail: mensajes, borradores y adjuntos.
  - Contactos.
  - Calendar.
  - Tareas.
  - Google Drive: listado/metadatos y contenido de archivos.
- Se añade una opción rápida de **Solo datos esenciales** para reducir el volumen de la copia.
- La barra del Centro de control muestra el progreso vivo de la copia, el servicio actual y el porcentaje.
- El progreso se actualiza también dentro de cada servicio grande, por ejemplo al recorrer mensajes de Gmail o archivos de Drive.
- El endpoint del Centro de control ahora expone el progreso real; ya no muestra 0 % simplemente porque la vista no recibía ese dato.
- Las copias siguen separadas por usuario y se mantienen en el almacenamiento persistente de ZAR.

## Importante
ZAR en Railway no puede leer automáticamente los archivos de todo el ordenador del usuario. Esta función copia los datos de Google autorizados. Si en el futuro se quiere una copia del PC, deberá ser una función independiente con selección de carpetas/archivos desde el propio dispositivo.

## Seguridad y límites
- No se inventan datos ni se marca como completado un servicio que haya fallado.
- Si Gmail o Drive tiene mucho contenido, la copia puede tardar; el progreso identifica qué está procesando.
- Los límites de tamaño de adjuntos/archivos siguen siendo configurables mediante las variables existentes.
