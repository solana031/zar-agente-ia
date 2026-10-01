# ZAR v32.0.1 — Market Quote Guard

Hotfix defensivo de ZAR Stonks v32.0.0.

- Descarta quotes con bid/ask ausentes o no positivos.
- Descarta mercados cruzados (`bid > ask`).
- Descarta spreads anómalos por encima del umbral configurable.
- Conserva el último trade/bar válido como fallback visual, pero marca la fila como `INVÁLIDO` y `market_usable=false`.
- Una quote válida posterior limpia el estado de invalidez.
- No modifica Risk, sizing, lifecycle, Paper Execution ni el bloqueo Live.
- Mantiene telemetría GPT/Gemini/Local/Coste IA de v32.
