# ZAR v27.34 — Compact context rail + focus mode

## Objetivo
Reducir el espacio permanente ocupado por el panel derecho sin perder acceso a sus controles.

## Cambios
- El panel derecho pasa de 292px a ~236px cuando está abierto.
- Nuevo botón de contraer/expandir.
- Al contraerlo queda una barra de 44px, recuperando casi todo el espacio para el chat/editor.
- El estado se guarda en `localStorage`.
- En la primera carga de esta versión se inicia contraído en escritorio.
- Atajo `Ctrl+B` (o `Cmd+B` en Mac), excepto dentro de campos de texto.
- Mantiene el Centro de control, Google, backup y demás herramientas sin eliminar funciones.
- En pantallas <=1100px el rail sigue ocultándose como antes para priorizar el contenido.

## UX
El panel derecho pasa a comportarse como un rail contextual: visible cuando se necesita y plegado durante trabajo de chat/editor.
