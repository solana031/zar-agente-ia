# ZAR v31.3.10 — Confirmación ZAR para bloqueos del ciclo Paper

Cambios:
- El ciclo `🧪 Probar ciclo Paper` ya no usa `alert()` del navegador cuando Risk bloquea la prueba o se produce un error.
- Los bloqueos como `Motor pausado`, `Control revocado`, mercado cerrado o modo incorrecto se muestran en el modal visual propio de ZAR Stonks.
- Se añade `zsOpenNotice()` reutilizando el modal ZAR existente y ocultando temporalmente el botón Cancelar para avisos informativos.
- Las denegaciones esperadas no se tratan como excepciones; se registran como `TEST PAPER · DENEGADA` y muestran el motivo.
- Se mantiene la lógica de ejecución Paper, Risk y kill switch sin cambios.
- Versión visual y archivos VERSION/VERSION.txt actualizados a 31.3.10.
