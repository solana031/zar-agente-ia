# ZAR v30.10.11 — Aprendizaje realmente continuo + UI de escritorio

- Reactiva automáticamente el worker persistente de aprendizaje al iniciar/reanudar y al consultar el estado.
- `/api/learning` y `/api/learning/<id>` ya no esperan a terminar una búsqueda: despiertan el worker y responden inmediatamente.
- El estado se sigue guardando después de cada lote para poder recuperar el aprendizaje tras reinicios de Railway.
- Progreso de aprendizaje visible en tiempo real, con consultas/fuentes y resaltado `EN CURSO` en el menú lateral.
- Compositor del chat elevado para no quedar oculto por la barra de tareas de Windows.
- Texto de `Habilidades activas` y `Aprendizaje en curso` ampliado y con varias líneas cuando sea necesario.
- Flechas ↑/↓ de navegación del chat siempre visibles y separadas del compositor.
- No se eliminan conversaciones, memoria, archivos ni datos persistentes.
