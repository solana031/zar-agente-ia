# ZAR 31.3.52 - Responsive polish y Stonks readiness

Base canonica: main 31.3.51 (4b2cd3d8257ce1e1d9b6727d481a26f58355fd03).

## Cambios

- PaperExecutionAdapter concentra los envios ya validados por Decision/Risk. Repite modo Paper, Shadow, pausa, revocacion y limites finitos antes del transporte. Endpoint y credenciales exclusivamente Paper.
- LIVE_TRADING_ENABLED es False en codigo, no una variable configurable. LiveExecutionAdapter rechaza su construccion. El servidor rechaza peticiones Live manipuladas y preflight/UI muestran el bloqueo.
- REAL MONEY READINESS es una lectura determinista, sin ordenes ni autoridad para modificar controles. Muestra 15 comprobaciones. La conexion exige reconciliacion reciente; credenciales solas no son evidencia. Validation Lab/walk-forward sin evidencia persistida y la evaluacion de tolerancia al drawdown permanecen pendientes. El estado global siempre es LIVE BLOQUEADO, incluso con muestra suficiente.
- Learning mantiene su journal JSON atomico y su historial completo; solo las metricas usan las ultimas 5000 operaciones. Un journal ilegible bloquea la ingesta sin sobrescribirlo. Se evita el reingreso circular por truncamiento, se exige ownership y resultados reconciliados finitos y se excluye TEST_LIFECYCLE. Ranking requiere al menos 20 operaciones por grupo. No altera Risk, permisos, SL/TP o Paper/Live. UI incluye muestra, drawdown, MAE/MFE, racha actual y ultimas 20 operaciones.
- Streams prioriza posiciones, ordenes, senales, watchlist y opciones explicitas. Conserva limites, backoff y fallback existentes. Un PID ajeno no puede forzar apertura de sockets; los snapshots persistidos vuelven a calcular stale y salud al leerse.
- Decision excluye barras 1/5/15 minutos no cerradas y rechaza precios sin timestamp verificable o con mas de 120 segundos. La cuenta debe estar ACTIVE y sin bloqueos. Cantidades no finitas son rechazadas en ordenes directas.
- Se corrige el cierre generico de Stonks (su display:flex!important lo mantenia visible sobre otras superficies) y se amplian a 44 px los botones tactiles de timeframe.
- Se restauran los accesos rotos a Mapas y Multimedia usando el panel y Studio existentes. No se cambia la estetica ni se reemplazan componentes.

## Arquitectura preservada

Un unico motor servidor, transaccion/ledger existentes, flock Linux, ciclo ~5 s, ownership y deduplicacion persistentes. Cerrar la UI no detiene el motor. No se habilitan shorts nuevos ni gestion de posiciones manuales. Pausa/revocacion conservan su prioridad sobre envios y la reconciliacion sigue disponible.

No se modifica OAuth, Railway, credenciales, datos persistentes, stashes ni el checkout anterior. Learning, readiness y ciclo habitual son deterministas a cero tokens; AI Gate permanece cerrado. Paper Learning ya estaba integrado en Orquestacion y se conserva.

## Validacion automatizada

Pytest con persistencia temporal y bloqueo de conexiones HTTP/socket; broker siempre mock. Regresiones nuevas cubren Live/Shadow/kill switch en transporte y peticiones, aprendizaje/retencion/ownership, limites de muestra, snapshots stale, prioridad multiactivo, PID entre procesos, velas cerradas y worker sin navegador.

Un test responsive reutilizable cubre 1920x1080, 1600x900, 1440x900, 1366x768, 1180x820, 1024x768, 820x1180, 768x1024, 430x932, 412x915, 393x852, 375x812 y 360x800. Incluye superficies existentes, tabs Stonks, reapertura, controles, IDs, overflow, errores JS, confirmacion, Studio, clusters de 10/20/40/60 agentes, landscape y viewport reducido. Screenshots solo ante fallos y fuera de Git. Se conservan las suites UI anteriores y su comprobacion de formularios Risk durante refresh/guardado.

Sin ordenes reales ni a una cuenta Paper conectada. La emulacion Chromium/standalone valida la superficie web, no certifica Android nativo. Este checkout no contiene proyecto Android. El lock flock se conserva; los tests Windows verifican exclusion por PID y concurrencia del motor, no ejecutan flock Linux.

La unica comprobacion manual pendiente tras despliegue es abrir ZAR en la PWA/WebView Android usada habitualmente, mostrar/ocultar teclado y volver a Stonks para confirmar safe-area, navegacion y readiness. No necesita enviar ordenes.


## Resultado final

- compileall Python, scripts inline y JavaScript externo: PASS.
- Suite completa pytest: 151 tests y 38 subtests PASS. Despues se anadio la regresion de journal corrupto; revalidacion focalizada: 31 tests y 6 subtests PASS. Total final de casos distintos: 152.
- stonks-rendering, focused-review-ui, general-ui y orchestration-layout-adaptive: PASS. Los fixtures antiguos de preflight y numero de accesos del dock se actualizaron conservando sus aserciones.
- Auditoria responsive: 452 comprobaciones iniciales; fallos limitados al cierre y tamano tactil de Stonks. Revalidacion focalizada final de Stonks: 153 comprobaciones PASS en los 13 tamanos; cierre/transicion a Orquestacion tambien revalidado. Sin volver a ejecutar la auditoria global ni pytest completo.
- Diff revisado y finales CRLF originales conservados en dos tests. Ninguna orden real, credencial, runtime ni screenshot incluido.

## Archivos de la publicacion

- VERSION, VERSION.txt, app/VERSION.txt.
- app/main.py; app/stonks_execution.py; app/stonks_readiness.py; app/stonks_learning.py; app/stonks_preflight.py; app/stonks_selftest.py; app/stonks_stream.py; app/stonks_dataplane.py.
- app/templates/index.html.
- tests/conftest.py; tests/responsive-audit.cjs; tests/test_stonks_readiness.py; tests/general-ui.cjs; tests/stonks-rendering.cjs; tests/test_stonks_learning.py; tests/test_stonks_learning_store.py; tests/test_stonks_lifecycle.py; tests/test_stonks_multiprocess.py.
- Este README.
