# ZAR v31.3.49 — Adaptive Orchestration Clusters

- Los clústeres/esferas de Orquestación crecen automáticamente según el número de agentes.
- El radio se calcula con separación mínima por nodo, evitando tener que reajustar el layout a mano en futuras versiones.
- El lienzo completo también aumenta cuando las esferas necesitan más espacio.
- ZAR general y ZAR Stonks mantienen centros independientes y separación dinámica.
- El anillo interno de Data Plane / Event Router / AI Gate / Self-Test también adapta su radio.
- Se conservan zoom semántico, rueda, pan, ventana redimensionable y trazas.
- No se toca memoria, Paper state ni lógica de órdenes.
