# ZAR 31.3.20 — Position Management Paper

## Arquitectura y propiedad

Se reutiliza `_stonks_engine_loop` en `app/main.py` (intervalo nominal ~5 s más el tiempo de las consultas). `app/stonks_lifecycle.py` contiene la máquina de estados, sin hilos ni scheduler propios. No depende del navegador.

El estado sigue en `ZAR_DATA_DIR/stonks/<scope_id>.json`, en el volumen persistente existente. `position_ledger` conserva cada episodio, su intención de entrada, estrategia, dirección y sus intenciones de salida. Las entradas `zar-e-…` y salidas `zar-x-…` tienen `client_order_id` único persistido **antes** del POST. La escritura es atómica (`fsync` + reemplazo); un lock de threads y de archivo en Linux serializa mutaciones del worker y las rutas operativas. El lock del worker permite relevo tras un reinicio de proceso.

El motor abre una nueva posición solo desde un símbolo sin posición ni órdenes pendientes. No aumenta posiciones existentes ni adopta posiciones manuales. La cantidad neta ejecutada de órdenes propias debe coincidir con la posición real. Se contrasta el historial de órdenes y se bloquea la gestión si hay actividad externa sobre el mismo episodio, aunque la cantidad neta coincida. No basta el prefijo del identificador: debe existir la intención persistida. Las posiciones heredadas de 31.3.19 sin baseline verificable se conservan como ERROR para revisión, sin cerrarlas automáticamente.

Las estrategias existentes siguen generando entradas LONG y pueden cerrar LONGs propios por señal SELL (`CERRANDO_SIGNAL`), incluso con SL/TP desactivado. Esta versión no añade una estrategia de entrada SHORT; la máquina de gestión soporta LONG/SHORT cuando existe ownership inequívoco. Las órdenes manuales siguen disponibles y no se convierten en propiedad del motor.

## Reconciliación, niveles y estados

Se consultan posiciones, órdenes abiertas y el historial completo desde el episodio activo más antiguo (con margen de reloj). El historial se pagina por ID; respuestas incompletas o errores bloquean envíos. Se incluyen símbolos retirados de la watchlist.

Los datos de entrada, precio, valor y P/L proceden de Alpaca. SL/TP se recalculan con `avg_entry_price` real y los porcentajes guardados actuales:

- LONG: SL = entrada × (1 − SL%); TP = entrada × (1 + TP%).
- SHORT: SL = entrada × (1 + SL%); TP = entrada × (1 − TP%).
- Distancia SL/TP: distancia direccional desde el precio actual, dividida por ese precio y expresada en %. Es negativa si se ha atravesado el nivel.

Se muestran ABIERTA, PROTEGIDA, CERRANDO_SL, CERRANDO_TP, CERRADA y ERROR; los motivos explican bloqueos. PROTEGIDA significa vigilancia de servidor, no un stop alojado en el broker. El precio de ejecución de una orden market no está garantizado; los límites de importe se verifican sobre el precio reconciliado.

Una orden enviada sin fills no se presenta como posición abierta. En fills parciales se registra la cantidad real; si salta un nivel, se solicita cancelar el remanente y se espera su reconciliación antes de cerrar. Se usa `filled_at` para apertura, o el timestamp de actualización observado para un fill parcial; en ese caso no se dispone de precisión por ejecución individual.

El cierre se confirma cuando los fills propios dejan cantidad neta cero y la posición ya no está en Alpaca. Un snapshot ausente o discrepante no basta. El registro cerrado permanece visible hasta el siguiente episodio del símbolo; el ledger mantiene los episodios anteriores.

## Risk, Pausa y Revocación

- Pausa y Revocación bloquean nuevas entradas **y nuevos cierres SL/TP**. Se mantiene la reconciliación y la UI indica protección suspendida. Se elige respetar el kill switch de forma estricta en Paper; no hay envíos ocultos bajo pausa.
- Revocar desactiva el motor, pero conserva su propietario para poder observar. Restaurar deja el motor pausado; para volver a operar hay que activar el motor y reanudar explícitamente.
- Motor desactivado, modo decisión y mercado cerrado también suspenden nuevos cierres automáticos.
- Órdenes previamente aceptadas pueden ejecutarse aun después de pausar/revocar. Siguen disponibles las cancelaciones de emergencia; pausa/revocación no las cancelan implícitamente.
- Se comprueban cuenta bloqueada, pérdida diaria máxima, importe máximo y porcentaje máximo de cartera. Alcanzar el límite diario suspende también el cierre y se muestra ERROR con el motivo. El importe/% limita cada tramo de salida; se reconcilia un tramo antes de enviar otro. No se sobrevende ni se cambia la dirección de la exposición. Un límite cero de importe, porcentaje o pérdida diaria bloquea nuevas órdenes; no se interpreta como autorización ilimitada.
- Los controles y envíos se serializan: la confirmación de Pausa/Revocación significa que el estado ya está guardado. Un envío en curso puede terminar antes de esa confirmación.

## Reinicios y duplicados

Al reiniciar se recuperan estado, propietario y client IDs del volumen y se consulta Alpaca. Mientras un cierre siga pendiente no se genera otro ID. Un timeout no implica rechazo: se busca primero el ID en Alpaca; solo un 404 confirmado permite reintentar el mismo ID, tras verificar Risk y cantidad. Nunca se genera un ID nuevo para resolver una respuesta incierta. Una salida rechazada queda en ERROR para revisión; una entrada de resultado desconocido se conserva y no se reenvía automáticamente.

La deduplicación de señales se guarda antes de enviar entradas. Un cierre parcial confirmado puede originar un siguiente tramo con su propio ID, sin coexistir con el anterior pendiente. Corrupción de estado, ownership ambiguo, historial truncado o pérdida del volumen no se resuelven adoptando posiciones por símbolo.

El Paper account debe evitar operaciones externas concurrentes en símbolos gestionados: Alpaca agrega posiciones por símbolo y no ofrece aislamiento de lotes entre clientes. Se detecta actividad externa y se bloquean nuevas órdenes, pero no puede deshacerse una orden ya aceptada que coincida con una intervención externa posterior. No se usan endpoints ni credenciales Live.

## Auditoría y validación

Eventos: POSITION_DETECTED, POSITION_PROTECTED, SL_TRIGGERED, TP_TRIGGERED, CLOSE_REQUESTED, POSITION_CLOSED y POSITION_ERROR, con símbolo, cantidad, precio y motivo disponibles. Se conserva la auditoría persistente existente (últimos 200 eventos), sin secretos.

Pruebas desde la raíz:

```text
python -m compileall -q app tests
python -m unittest discover -s tests -p "test_*.py" -v
node tests/stonks-rendering.cjs
git diff --check
```

El navegador requiere Node, Playwright y Chromium; `ZAR_TEST_BROWSER` admite un ejecutable instalado. Los tests Python aíslan el control-plane Flask del resto de servicios al compilar sus funciones reales; los tests de navegador interceptan toda la red. No crean órdenes en ninguna cuenta. La UI actualiza celdas sin reemplazar filas, recargar la página ni insertar texto de broker como HTML.

Pendiente tras despliegue: verificar Railway y observar reconciliación de una cuenta Paper configurada, sin abrir operaciones únicamente para validar. Los tests no certifican disponibilidad de Alpaca, montaje real del volumen ni fills reales. Se mantiene la limitación móvil de ancho ya documentada en 31.3.19.

Referencias de contrato: [órdenes e identificadores](https://docs.alpaca.markets/us/docs/working-with-orders), [consulta por client_order_id](https://docs.alpaca.markets/us/reference/getorderbyclientorderid), [historial paginado](https://docs.alpaca.markets/us/reference/getallorders-1).
