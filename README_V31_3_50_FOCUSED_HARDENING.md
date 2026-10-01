# ZAR v31.3.50 — Focused Review Hardening

Integración de la revisión focalizada de Codex sobre 31.3.49.

- Shadow bloquea cualquier ruta de órdenes Paper.
- Cachés Data Plane acotadas y misses concurrentes colapsados.
- Streams con backoff, control de carreras y lifecycle de threads.
- Datos stale identificados y no presentados como recientes.
- Outcome usa barras cerradas, deduplicadas y paginadas.
- Shadow no duplica la misma señal cada ciclo de 5 s.
- Drawdown incluye el capital inicial.
- Orquestación conserva correctamente tamaño/posición al reabrir.
- Guardado Risk no pisa una edición posterior.

Sin cambios de funcionalidad nueva ni conexión Live.
