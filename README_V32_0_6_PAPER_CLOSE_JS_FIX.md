# ZAR v32.0.6 — Paper Close JS Fix

- Restaura `zsRenderBlockingPaperAction()` y `zsCloseBlockingPaperPosition()` en la interfaz Stonks.
- Muestra una acción primaria y visible en móvil para cerrar la única posición Alpaca Paper bloqueante.
- El backend vuelve a verificar exactamente 1 posición, 0 órdenes abiertas, símbolo y cantidad antes del SELL Paper.
- LIVE permanece bloqueado.
- Conserva Workspace Pro de v32.0.4+ y el resto de v32.0.5.
