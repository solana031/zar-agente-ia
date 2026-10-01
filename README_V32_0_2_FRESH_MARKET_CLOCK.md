# ZAR v32.0.2 — Fresh Market Clock

Hotfix de observabilidad de ZAR Stonks.

- Orquestación deja de presentar el último estado persistido de Market Data como si fuese actual.
- Cada carga/refresco de Orquestación consulta un reloj fresco de Alpaca Paper.
- Valida `is_open` y el timestamp del broker; un reloj inválido/obsoleto se muestra como no disponible, nunca como «Mercado cerrado».
- Las vistas directas de quote/portfolio reutilizan el mismo reloj validado.
- No concede autoridad de órdenes al panel de Orquestación.
- No modifica Risk, sizing, lifecycle, Paper Quality Guard, Shadow ni el bloqueo LIVE.
