# ZAR v31.3.5 — Decision Hardening

Basada en v31.3.4. Mantiene Stonks Paper-only y endurece la frontera entre evaluación y ejecución.

- `/api/stonks/decision` requiere `paper_auto` o `manual_confirmed=true` para ejecutar.
- La evaluación Risk sin órdenes sigue siendo el modo predeterminado.
- Se mantiene pausa/revocación como kill switch.
- Se mantienen deduplicación, límites de operación, pérdida diaria y posición.
- Etiquetas de límites del panel ajustadas a USD porque la cuenta Alpaca Paper opera en USD.
- Live sigue desconectado.
