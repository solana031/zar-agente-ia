# ZAR v30.4.2 — Habilidades integradas en el chat

Esta versión mejora el sistema de Habilidades de ZAR sin cambiar su almacenamiento persistente.

## Cambios
- Ejecutar una habilidad desde el panel lleva automáticamente al chat principal.
- El trabajo solicitado y el resultado de la habilidad aparecen directamente en el chat.
- El resultado de una habilidad puede seguir usando las tarjetas especiales de Gmail/Workspace y las confirmaciones existentes.
- El chat muestra una banda compacta con las habilidades activas en ese momento.
- La banda se actualiza después de cada respuesta y al consultar las habilidades.
- Las habilidades activas siguen pudiéndose invocar desde el cuadro de texto normal mediante su nombre/frase de activación.
- Se mantiene el almacenamiento por usuario en `ZAR_DATA_DIR/users/<usuario>/skills/skills.json`.

## Persistencia
No se incluye `data/`, usuarios, bases SQLite, backups ni tokens en el release.
