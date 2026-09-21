# ZAR v30.10.1 — reanudación de aprendizajes

Corrección de la UI y del estado de reanudación de aprendizajes.

- El botón Reanudar desaparece inmediatamente al pulsarlo.
- Se muestra Reanudando… mientras arranca el worker.
- Las respuestas concurrentes de estado no vuelven a pintar el botón durante la transición.
- El backend publica estado activo antes de iniciar el worker.
- Se mantiene la confirmación propia de ZAR para eliminar aprendizajes.
