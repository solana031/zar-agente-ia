# ZAR v31.3.15 — Capital Paper con transición animada

## Objetivo
Evitar que el valor de «Capital bot» desaparezca y reaparezca cada 5 segundos durante la sincronización automática.

## Cambios
- El valor anterior se conserva visualmente durante la actualización.
- Cuando cambia el equity, el número transiciona progresivamente hasta el nuevo valor durante ~850 ms.
- Una subida o bajada activa una animación sutil para que el cambio sea perceptible sin parpadeo.
- Si el valor no cambia, no se reinicia la animación.
- La sincronización automática de 5 s se mantiene.
- Motor autónomo Paper continuo y controles Risk no se modifican.
- Live continúa desconectado.

## Validación
- Python/JS: validar tras empaquetado.
- ZIP: validar con unzip -tq.
