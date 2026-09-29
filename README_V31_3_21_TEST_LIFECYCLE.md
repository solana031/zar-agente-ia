# ZAR 31.3.21 — Prueba controlada de Position Lifecycle Paper

En Configuración Risk > Gestión de posición Paper se añaden «Probar ciclo Paper», «Cerrar prueba Paper» y un indicador de seis pasos confirmados por el servidor. Los datos de la posición aparecen en la tabla de Position Management existente, con origen TEST_LIFECYCLE.

## Requisitos y tamaño

La UI habilita el inicio cuando la reconciliación ha verificado una cuenta Alpaca Paper ACTIVE y operativa, el usuario es propietario del motor servidor activo, están habilitados Paper automático y Gestión de posición, y no hay Pausa ni Revocación. El servidor vuelve a comprobar las condiciones; una UI antigua no puede saltarse los controles.

La entrada es una compra market/day de **1,00 USD de notional**, solo sobre un activo US equity activo, tradable y fractionable según Alpaca. Debe caber en el límite por operación, porcentaje de cartera, saldo disponible y pérdida diaria. Un límite insuficiente, mercado cerrado, posición previa u orden pendiente en ese símbolo deniega la prueba; nunca se aumenta el tamaño ni se toman posiciones manuales. La cantidad definitiva se obtiene del fill, no del precio usado para estimar Risk. No se consulta ni utiliza Live.

Contrato de referencia: [Alpaca Fractional Trading](https://docs.alpaca.markets/us/docs/fractional-trading) admite operaciones fraccionarias desde 1 USD y órdenes notional/day. No se envían simultáneamente qty y notional.

## Recorrido de producción

`POST /api/stonks/lifecycle-test/start` requiere confirmación explícita y un UUID de solicitud. Invoca la misma función Decision/Risk de producción mediante una opción interna, inaccesible por parámetros del endpoint público. Solo sustituye la fuente de señal por una decisión sintética identificada como TEST_LIFECYCLE y limita el notional; mantiene los controles y el mecanismo común de envío.

El ledger existente guarda el propósito TEST_LIFECYCLE, UUID de solicitud, client_order_id, ownership y pasos antes del POST de entrada. La orden enviada no se considera ejecutada. El worker existente reconcilia fills, posición, cantidad neta y ownership, incluso con el navegador cerrado. No se crea otro motor ni otro almacén de estado.

`POST /api/stonks/lifecycle-test/close` solo acepta el ID de una prueba propia reconocida y confirmación explícita. Guarda una solicitud de cierre (`trigger=TEST`); **no envía una orden directamente**. El mismo worker vuelve a comprobar posición, órdenes y Risk antes de crear el cierre mediante el ledger y client_order_id existentes. En fills parciales se utiliza el tratamiento de cancelación del remanente y reconciliación de 31.3.20. El estado final OK exige fills propios de salida reconciliados y ausencia de la posición en Alpaca.

No se alteran los porcentajes SL/TP normales: también protegen la posición de prueba si llegan a alcanzarse. El botón de cierre permite verificar el recorrido sin esperar un movimiento de mercado. Las señales ordinarias SELL no cierran el episodio TEST_LIFECYCLE; el motor normal sigue activo para los demás símbolos y, después de finalizar la prueba, puede volver a operar ese símbolo según sus señales.

## Duplicados, errores y reinicios

- Solo una prueba activa por propietario del motor. El lock de producción serializa inicios simultáneos.
- Repetir un UUID de inicio devuelve el estado ya existente, incluso si terminó; nunca crea otra entrada. Una nueva prueba requiere otro UUID.
- Pulsaciones repetidas de cierre conservan la misma solicitud y las intenciones de salida existentes.
- Tras reinicio, todo se recupera del volumen y del ledger. Se mantienen las reglas de 31.3.20 para recuperar órdenes por client_order_id y para reintentar una salida incierta sin cambiar el identificador.
- Un timeout no significa rechazo. Una entrada de resultado desconocido sigue bloqueando nuevas pruebas hasta reconciliarse; si Alpaca nunca confirma su existencia, queda ERROR para revisión y no se borra automáticamente.
- Un rechazo/cancelación terminal sin fill termina la prueba con ERROR, nunca con OK. Una salida rechazada o un conflicto con actividad manual mantiene el bloqueo para revisión.
- Pausa/Revocación bloquean nuevos inicios y nuevos envíos de cierre, incluso con una solicitud ya guardada. La reconciliación continúa. Órdenes previamente aceptadas pueden ejecutarse. Tras reanudar, una solicitud de cierre pendiente vuelve a evaluarse con Risk.
- Los bloqueos Risk del cierre aparecen en el estado de la prueba; el botón no los evita. La ausencia temporal de respuesta de cuenta deshabilita la conexión verificada de UI, sin impedir intentar la reconciliación observacional de posiciones.

## Auditoría

En el mismo registro existente: TEST_LIFECYCLE_STARTED, TEST_ENTRY_REQUESTED, TEST_POSITION_DETECTED, TEST_CLOSE_REQUESTED, TEST_POSITION_CLOSED, TEST_LIFECYCLE_OK y TEST_LIFECYCLE_ERROR. Los hitos también se conservan en cada episodio del ledger para que la UI sobreviva al reinicio y al límite histórico de la auditoría general. No se registran secretos ni cuerpos de error del broker.

## Validación

```text
python -m compileall -q app tests
python -m unittest discover -s tests -p "test_*.py" -v
node tests/stonks-rendering.cjs
git diff --check
```

Los tests nuevos en `tests/test_stonks_controlled_lifecycle.py` usan el control-plane Flask y worker reales con APIs simuladas: inicio, notional, ownership, fill, cierre, auditoría, respuestas tardías, duplicados, concurrencia, reinicio, errores, pausa/revocación, Risk y posiciones manuales. Los tests anteriores se conservan; su mock de reconciliación ahora incluye la consulta de cuenta.

El test de navegador comprueba los botones, requisitos, confirmaciones, pasos y el resto del dashboard/chat. Toda la red está interceptada. No se ejecutan órdenes en ninguna cuenta durante las pruebas automatizadas. Se conserva la limitación previa de interacción en teléfonos estrechos; el DOM y la tabla móvil se verifican, sin afirmar que esa incidencia quedó resuelta.

Pendiente tras publicación: comprobar el despliegue Railway y, solo por decisión expresa del usuario mediante la nueva UI, ejecutar el ciclo en su cuenta Paper. Esta implementación no activa el motor, no reanuda ZAR, no cambia SL/TP, no modifica Railway y no lanza la prueba al desplegar.
