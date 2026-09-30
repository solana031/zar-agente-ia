# ZAR 31.3.23 — General UI UX Polish

Base: 31.3.22, commit e29a46674b07666d711219c577c246b30960902b. Se conservan logo, paleta negra/marrón/dorada, funciones y backend.

## Problemas encontrados y corregidos

- Home: reglas desktop eran la única fuente de estilo de los accesos; la cuadrícula se ocultaba en teléfonos y aparecía sin estilo en tablet. Ahora las nueve funciones son visibles, con rejillas de tres columnas, nombres que pueden envolver y targets legibles. Se conservan los slots y Personalizar funciones. En desktop se mantienen las dos rejillas 3x3 y el logo central, reduciendo truncados al abrir los paneles laterales.
- Cabecera: el botón Volver aparecía incluso en Home, mientras Ajustes no era accesible en móvil. Se ajusta su visibilidad según el espacio abierto; la cabecera mantiene el menú y los accesos.
- Tablet: el menú hamburguesa cambiaba una sidebar que quedaba fuera del flujo útil. Ahora usa el drawer hasta 1100 px, con scroll, aria-expanded, Escape y capa por encima de su fondo.
- Composer: el desktop podía exceder el borde inferior en 8 px. Se elimina su altura rígida. En móvil se mantienen textarea, adjuntos, micrófono, mute, envío y accesos rápidos, con medidas adaptables y offsets de VisualViewport para teclado. Se conserva el borrador.
- Paneles generales: altura limitada al viewport visible, scroll interior y cierre accesible. El composer general se oculta mientras hay un panel y se restaura al cerrarlo. Stonks conserva su contenedor y estilos específicos.
- Studio: se recuperan las acciones de cabecera ocultas en móvil, se corrige el ancho de tablet, se contienen editores y pistas y se añade cierre explícito al panel contextual de hora/calendario/tiempo. El atributo hidden vuelve a ocultar ese panel vacío. No se cambia el backend, renderizado multimedia ni operaciones de edición.
- Tema claro: superficies y textos coherentes en Home, composer, menú, ajustes, paneles y Aprendizajes. Se corrige el texto oscuro sobre el composer negro.
- Accesibilidad: focus visible, estados disabled, controles táctiles mayores y nombres accesibles del textarea y cierre.

## Archivos

- app/static/ui-polish.css: ajustes de presentación aislados.
- app/static/ui-polish.js: viewport visible, estado accesible del menú y cierre contextual Studio; sin llamadas de red.
- app/templates/index.html: carga de recursos, estado abierto del panel, breakpoint del menú y etiquetas de versión.
- tests/general-ui.cjs: nueva suite general con red interceptada.
- tests/stonks-rendering.cjs: versión objetivo y carga de los recursos nuevos para comprobar regresiones reales.
- VERSION, VERSION.txt, app/VERSION.txt: 31.3.23.

## Validación

- Python: `python -m compileall -q app tests` y 59 tests con `python -m unittest discover -s tests -p 'test_*.py' -q`.
- Navegador: `node tests/general-ui.cjs` y `node tests/stonks-rendering.cjs`, Playwright/Chromium con todas las respuestas simuladas; sintaxis JS externo e inline comprobada.
- Resoluciones: 360x800, 390x844, 412x915, 430x932, 768x1024, 1440x900 y 1920x1080. Adicionalmente 800x430, 360x400 y VisualViewport simulado a 350 px.
- Home, Personalizar, apertura/cierre de menú, accesibilidad de sus botones, composer y file chooser, reflow de laterales, Calendario, Archivos, Tiempo, Memoria, Tareas, Control, Investigación, Contactos, Workspace, Gmail, Hora, herramientas, ayuda, ajustes, Aprendizajes, Studio (imagen, vídeo con timeline y audio con pistas), tema claro/oscuro y errores de servicio.
- Sin overflow horizontal global en los escenarios probados. Paneles y modales dentro del viewport; timelines pueden tener scroll local.
- Stonks conserva pruebas de desktop/móvil, navegación, chat, Risk, Position Management, TEST_LIFECYCLE, tablas, sincronización y cierre/reapertura.
- Diff y diff staged revisados; no se modifican archivos Python, OAuth, aprendizaje, memoria ni lógica de trading. Live permanece desconectado. Ninguna orden Alpaca durante los tests.

## Alcance de Android/PWA y pendientes

Los cambios son web y usan VisualViewport con fallback a innerHeight. No se toca zar-android. No se ha identificado un defecto exclusivamente nativo mediante estas pruebas; queda pendiente la comprobación física de teclado/IME, barras del sistema, safe areas, dictado y selector de archivos en la WebView instalada y en Safari/iOS. El viewport/teclado automatizado es una simulación, no una certificación de dispositivos físicos. No se prueba OAuth real ni servicios conectados, ni se envían mensajes externos. Railway no se modifica manualmente y el despliegue no se considera verificado solo por el push.
