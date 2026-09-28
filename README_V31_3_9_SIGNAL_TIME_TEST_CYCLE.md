# ZAR v31.3.9 — Signal timestamps + Paper test cycle

Cambios:
- El Registro IA en vivo ya no muestra "Ahora". Todas las entradas muestran fecha y hora exactas de Madrid con segundos (dd/mm/aaaa HH:mm:ss).
- Las entradas iniciales del panel reciben su hora real al abrir ZAR Stonks.
- Añadido botón `🧪 Probar ciclo Paper` en Estrategias IA.
- La prueba es explícita y confirmada con el modal propio de ZAR.
- La prueba no depende de que SMA20/50 o RSI produzcan una señal real.
- El backend ejecuta una compra sintética de aproximadamente 1 USD en Alpaca Paper y pasa por los controles operativos/Risk antes de enviar la orden.
- La prueba queda auditada como `TEST_PAPER` con order_id y estado.
- Nunca conecta con Alpaca Live.
- PAUSAR/REVOCAR tienen prioridad y Paper automático/Risk debe estar activo.

Prueba recomendada:
1. Mantener `Paper automático · con Risk` y ZAR reanudado.
2. Pulsar `🧪 Probar ciclo Paper`.
3. Confirmar en el modal ZAR.
4. Verificar `TEST PAPER`, `order_id`, estado en Órdenes y la posición Paper.
5. Después, gestionar/cerrar la posición de prueba antes de seguir con automatización.
