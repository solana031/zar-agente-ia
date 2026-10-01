# ZAR v32.0.7 — Template hotfix

Corrige el 500 al cargar `/` introducido en 32.0.6.

Causa: Jinja interpretaba la secuencia CSS `{#` del selector móvil como inicio de comentario de plantilla (`Missing end of comment tag`).

Cambio: se evita esa secuencia en el bloque responsive de Stonks sin alterar la funcionalidad de cierre Paper ni Workspace Pro.
