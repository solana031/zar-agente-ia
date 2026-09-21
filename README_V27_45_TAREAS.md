# ZAR v27.45 — Tareas

Corrección de la tarjeta Tareas en la interfaz web premium.

- La tarjeta Tareas abre siempre un panel propio.
- Muestra estado de Google Tasks.
- Lista tareas agrupadas por lista.
- Muestra pendientes y completadas.
- Muestra un estado vacío claro cuando no hay tareas.
- Si Google Tasks no está autorizado, ofrece reconectar Google.
- Se añade `usePrompt()` para que los accesos rápidos del compositor funcionen de forma consistente.

Nota: la integración existente usa el alcance `tasks.readonly`, por lo que esta versión corrige la consulta/visualización; la creación, edición y completado de tareas requiere ampliar el alcance y añadir las operaciones correspondientes en una versión posterior.
