# ZAR 31.3.22 — Mobile Stonks UI Fix

## Causas

La ventana flotante imponía min-width de 520/460 px incluso en teléfonos de 360 px. Las reglas móviles ocultaban la sidebar y todas sus secciones de navegación. La geometría y varios overrides antiguos repartían el scroll entre ventana, workspace y contenido. El composer general (capas 1200–2000) y la sidebar general (1000) podían quedar por encima de Stonks (900).

## Solución de interfaz

Un bloque CSS limitado a Stonks adapta teléfonos y tablets hasta 900 px, incluyendo el requisito de <=720 px: ventana de ancho completo, min-width:0, 100dvh, sin resize ni arrastre, sin radios y con safe-area. El cierre de Stonks permanece accesible y se oculta el cierre genérico duplicado de ese panel.

Se reutiliza el mismo menú de seis secciones en una fila horizontal desplazable, con sección activa destacada. Capital Bot conserva su elemento y animación. El contenido central tiene scroll vertical; tablas anchas y navegación tienen scroll horizontal propio. KPIs usan dos columnas (una hasta 340 px); gráficos, formularios, Risk, auditoría y composer se ajustan al ancho disponible. El chat ocupa espacio en el layout sin cubrir el dashboard.

Mientras Stonks está abierto, el composer general, sus accesos rápidos y los controles flotantes de chat quedan ocultos e inactivos por CSS; al cerrar se restauran sin eliminar nodos ni funciones. La ventana compacta se sitúa por encima de la sidebar general. No se guarda su geometría móvil como geometría desktop. Desktop conserva su sidebar, ventana y controles.

## Alcance preservado

No se modifica Python, las rutas API, el motor, Decision/Risk, ledger, ownership, client_order_id, reconciliación, SL/TP, Pausa/Revocación ni TEST_LIFECYCLE. La entrada de prueba de 1 USD y su cierre conservan el flujo de 31.3.21. Live sigue desconectado. No se cambia Railway ni Zar Studio.

## Validación

- `python -m compileall -q app tests`: correcto.
- `python -m unittest discover -s tests -p 'test_*.py' -q`: 59 tests aprobados con mocks.
- `node tests/stonks-rendering.cjs`: sintaxis de 17 scripts inline y JS externo, tres VERSION y tests del navegador.
- Resoluciones: 360x800, 390x844, 412x915, 430x932, 768x1024, 1440x900 y 1920x1080. Se cambia además a 800x430 y se vuelve a la resolución original con la ventana abierta.
- Sin overflow horizontal global en todas las vistas; ventana, cabecera, composer y KPIs contenidos; navegación por clics, tabla larga desplazable, chat, guardado Risk, botones y seis pasos TEST_LIFECYCLE, cierre/reapertura, restauración del composer, sincronización sin reemplazar filas, IDs y errores JS.
- Red completamente interceptada. Ninguna orden Alpaca enviada. Capturas locales inspeccionadas.
- Revisión del diff y `git diff --check` antes de publicar.

La validación usa Chromium/Edge automatizado con viewport simulado; no sustituye una prueba física en Safari/iOS o Android con teclado y recortes de pantalla. El despliegue de Railway no se verifica en esta tarea.
