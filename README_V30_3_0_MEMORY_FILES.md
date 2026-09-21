# ZAR v30.3.0 — Memoria + Archivos 2.0

## Objetivo
Convertir la memoria y la biblioteca de archivos de ZAR en un sistema de conocimiento persistente, buscable y verificable, sin romper las funciones de versiones anteriores.

## Cambios principales
- Búsqueda global sobre conversaciones, memoria y fuentes conectadas/indexadas.
- El explorador de archivos busca también dentro del contenido indexado de documentos, no solo por nombre, categoría o nota.
- Estado de indexación visible por archivo: Guardado, Indexando, Indexado o Error.
- Reindexación manual de un archivo desde el explorador cuando el índice falla o no está disponible.
- Eliminación de un archivo también elimina su fuente del índice local de conocimiento.
- Detección de duplicados mediante SHA-256 al subir archivos; un archivo idéntico no se almacena dos veces.
- El sistema informa de los duplicados detectados durante una subida.
- Persistencia separada del código: las actualizaciones de ZAR no sustituyen los datos de usuario.
- Se conserva el índice local SQLite por usuario y funciona sin depender de Google para recuperar conocimiento local.

## Conservación
La actualización no incluye ni sobrescribe la carpeta `data/`. En Railway, la persistencia real entre despliegues requiere el Volume montado en `/data`.

## Compatibilidad
Se mantienen Deep Research 2.0, Gmail UI, Google, backup seleccionable, conversaciones, memoria, archivos, Studio, voz y el resto de funcionalidades presentes en v30.2.8.
