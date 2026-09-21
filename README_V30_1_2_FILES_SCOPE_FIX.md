# ZAR v30.1.2 — Fix de almacenamiento por usuario

Corrige un fallo de v30.1.1: `FILES_DIR` se calculaba al importar Python, antes de que Flask estableciera el usuario activo de la petición. La subida usaba la ruta dinámica, pero análisis/previsualización/descarga/indexación podían buscar en `anonymous/files`.

Ahora todas las operaciones resuelven `files_dir()` en tiempo de ejecución usando el usuario activo. Esto mantiene aislados los archivos por sesión/cuenta y permite que el chat analice inmediatamente los archivos recién adjuntados.
