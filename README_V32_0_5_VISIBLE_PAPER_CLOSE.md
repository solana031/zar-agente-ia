# ZAR v32.0.5 — Visible Paper Close

- Acción prominente en Carteras & API para cerrar la única posición Paper bloqueante.
- Visible en móvil justo debajo de Posiciones Paper.
- Requiere confirmación explícita.
- El servidor revalida exactamente 1 posición Paper y 0 órdenes abiertas antes de enviar SELL.
- Revalida símbolo y cantidad para evitar cierres sobre estado cambiado.
- Solo usa `paper-api.alpaca.markets`; LIVE sigue bloqueado.
- Conserva Workspace Pro de v32.0.4.
