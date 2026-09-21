# ZAR v30.10.5 — reparación del aprendizaje y reanudación

Corrige el fallo de `elapsed_now`/`dynamic_estimate` que impedía reanudar el aprendizaje y podía marcar un error como 100%.

- Calcula tiempo y estimación antes de persistir el primer estado.
- Los errores conservan el progreso real y quedan reintentables.
- Reanudar/reintentar conserva `query_index` y continúa desde el último punto guardado.
- La UI muestra `Reintentar` para aprendizajes con error.
- Un error nunca se representa como 100% completado.
