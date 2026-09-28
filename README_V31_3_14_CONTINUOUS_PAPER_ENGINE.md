# ZAR v31.3.14 — Motor autónomo Paper continuo

## Cambio principal
El motor autónomo Paper deja de trabajar con un ciclo fijo de 30 segundos y pasa a ejecutarse de forma persistente en segundo plano, independientemente de que la ventana de ZAR Stonks esté abierta.

## Funcionamiento
- Worker servidor persistente.
- Supervisa el estado del motor cada ~5 segundos por defecto.
- `ZAR_STONKS_ENGINE_INTERVAL` permite ajustar el intervalo desde Railway; mínimo 2 segundos.
- La ventana de Stonks puede estar cerrada: el motor no depende del navegador.
- El motor sigue reaccionando únicamente a señales de barras cerradas; no genera órdenes repetidas en cada ciclo gracias al control de duplicados de Decision + Risk.
- Si el mercado está cerrado, no envía órdenes.
- Si PAUSA o REVOCAR están activos, no ejecuta.
- Solo puede enviar órdenes a Alpaca Paper. Live continúa desconectado.

## Seguridad
Se mantiene el bloqueo de un único propietario de la cuenta Paper y el `flock` para evitar que varios workers de Gunicorn ejecuten el mismo ciclo simultáneamente.

## Nota sobre “constante”
“Continuo” aquí significa supervisión persistente de baja latencia, no un bucle sin espera. Un intervalo de ~5 s evita una consulta de red en cada iteración del proceso y permite reaccionar rápidamente sin convertir el worker en un bucle agresivo.

## Verificación
- Python `py_compile`: correcto.
- JavaScript extraído y comprobado con `node --check`: correcto.
- ZIP validado con `unzip -tq`: correcto.
