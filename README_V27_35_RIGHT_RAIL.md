# ZAR v27.35 — Right rail redesign + adaptive desktop UI

## Objetivo
Corregir la interfaz de escritorio del panel contextual derecho. La v27.34 estaba mostrando el `mobileDrawer` también en escritorio, generando un segundo panel superpuesto y clipping horizontal.

## Cambios
- El drawer móvil queda exclusivamente para móvil/tablet y nunca se renderiza como segundo panel en escritorio.
- El rail derecho de escritorio pasa a 300 px (276 px en ventanas de 1101–1250 px).
- El contenido del rail se fuerza a una sola columna para evitar botones partidos o desplazamiento horizontal.
- `overflow-x:hidden` en todos los niveles relevantes.
- En modo contraído solo queda una pestaña de 46 px con el control de apertura.
- En modo expandido se muestran completos los botones y secciones.
- Se mantiene `Ctrl+B` / `Cmd+B` y la preferencia guardada en `localStorage`.
- Se conserva todo el backend y las funciones existentes.

## Verificación
- Sintaxis Python comprobada.
- Bloques JavaScript comprobados con Node.
