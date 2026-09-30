ZAR v31.3.37 · ORCHESTRATION FINAL WORKSPACE FIX

- Orquestación de Subagentes pasa a ser un workspace HTML fijo e independiente.
- Ya no reutiliza panelBody ni la última pestaña/panel abierto.
- Se añade un modo .orchestration-mode completo con visibilidad propia.
- Abrir cualquier panel normal cierra primero Orquestación para evitar solapamientos.
- Studio y Centro de Control también cierran Orquestación explícitamente.
- Se conserva el mapa espacial HUD/Jarvis, zoom, conexiones, etiquetas y replay temporal.
- No se modifica memoria persistente, datos Paper ni runtime.
