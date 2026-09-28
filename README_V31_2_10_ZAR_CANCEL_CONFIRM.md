# ZAR v31.2.10 — Confirmación ZAR para cancelación de órdenes Paper

## Cambio
La cancelación de órdenes Paper ya no usa `window.confirm()` del navegador.

Ahora reutiliza el modal visual de ZAR Stonks y muestra:
- título «Cancelar orden Paper»
- detalle de la orden/acción
- aviso de que solo afecta a Alpaca Paper
- botón «Mantener orden»
- botón de peligro «Sí, cancelar orden»
- icono de cancelación integrado en el estilo ZAR

## Conservado
- Flujo de envío Paper de v31.2.9.
- Modal propio de ZAR para confirmar envíos.
- Corrección del mínimo de Alpaca (orden de prueba de 1 USD).
- Historial y cancelación mediante `DELETE /api/stonks/alpaca/order/<order_id>`.
- Layout de Stonks y chat inferior.

## Verificación
- `app/main.py` compila con `py_compile`.
- JavaScript extraído de `index.html` pasa `node --check`.
