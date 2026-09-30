# ZAR v31.2.9 — Confirmación ZAR + mínimo Alpaca Paper

Cambios respecto a v31.2.8:

- Sustituye la confirmación nativa del navegador (`confirm()`) de las órdenes Paper por una ventana de confirmación integrada en ZAR Stonks.
- La ventana muestra claramente símbolo, lado, cantidad, tipo, precio y Time in Force.
- El botón de confirmación es propio de ZAR y no aparece como desplegable del navegador.
- El valor por defecto de la prueba Paper pasa a 1 AAPL a 1,00 USD, cuyo valor nominal es 1,00 USD.
- El backend valida antes de llamar a Alpaca que el valor de una orden sea al menos 1,00 USD y devuelve un mensaje claro si no se cumple.
- Para órdenes de mercado también se valida el mínimo de 1,00 USD usando el último precio disponible.
- Se mantiene Paper-only: no se conecta a Live ni expone credenciales al navegador.
- Se mantiene el diseño flex de v31.2.7/v31.2.8, con el chat y compositor en la parte inferior.

## Prueba recomendada

1. Desplegar el ZIP sin modificar el workflow.
2. Abrir ZAR Stonks → Órdenes.
3. Dejar los valores por defecto: AAPL / Comprar / Limit / 1 / 1,00 USD / DAY.
4. Pulsar «Enviar orden Paper».
5. Debe aparecer la nueva ventana de confirmación de ZAR.
6. Pulsar «Confirmar y enviar».
7. Pulsar «Actualizar órdenes» y comprobar que Alpaca devuelve la orden.
8. Cancelar la orden desde ZAR.
