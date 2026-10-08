# ZAR 33.3.9

Entrega incremental sobre 33.3.8. Conserva las identidades oficiales, los archivos persistentes y Automaton exclusivamente para trading Paper, con Live bloqueado.

## Bloques implementados

- Semantic Planner V2: plan visible, dependencias anteriores al consumidor, desambiguación de correo, referencias acreditadas a tareas y archivos, selección ante ambigüedad y condiciones visibles antes de enviar. El modelo configurado puede mejorar el plan; su JSON se valida y no puede omitir acciones solicitadas ni añadir envíos o lecturas de correo. Sin un plan válido conserva el plan contextual. Una referencia no acreditada queda WAITING.
- Superficie común `ZarUI` para confirmación, aviso, edición y selección. Los workflows frontend usan promesas explícitas; no se sustituyen las funciones síncronas del navegador por promesas. Media conserva el vídeo previo al editar/regenerar.
- Confirmaciones del chat persistentes por cuenta, vinculadas al payload exacto, con claim único de ejecución. HIGH/CRITICAL necesitan dos decisiones separadas. El botón registra SYSTEM/ACTION_CONFIRMED, nunca un mensaje artificial del usuario. El borrado de conversaciones utiliza la misma doble revisión persistente.
- StonksRealtimeBus: eventos del WebSocket Alpaca existente → SSE interno → actualizaciones acotadas por `requestAnimationFrame`. Riesgo y telemetría proceden del motor del servidor. La UI conserva formularios y solo actualiza componentes afectados. No hay refresh global cada cinco segundos. Los datos de mercado y telemetría no llaman al modelo.
- Sin un stream de eventos broker disponible, un observador compartido consulta cartera/órdenes cada 20 segundos mientras hay una ventana suscrita. Las conexiones SSE tienen límite de dos por proceso y duración acotada; en servidores síncronos se usa snapshot incremental con reconexión y backoff. No se cambia la configuración de Railway.
- BTC/USD: OHLCV Alpaca real, histórico una vez por ventana/periodo, seis timeframes, actualizaciones de ticks confirmados, hover, zoom y resize. La etiqueta distingue histórico/delayed de ticks recientes. Sin datos confirmados muestra el fallo; nunca fabrica una curva.
- Órdenes/Backtesting: campos normalizados y cifras principales legibles. Automaton: tarjetas de Wallet y broker, histórico en tabla y JSON técnico colapsado. Cerrar la UI no detiene el motor del servidor.
- Orquestación: corrección del `completed_tasks.length` indefinido, datos opcionales seguros y layout compacto por dominio con espacios proporcionales. Se conservan zoom extremo, pan, fit, resumen y persistencia.
- Mapas: Leaflet 1.9.4 incluido localmente y tiles OpenStreetMap visibles inicialmente en Madrid. Usa ubicación solo si el permiso ya está concedido. Conserva búsqueda Google y rutas externas; permite marcar coordenadas y puntos. Si Google no está configurado ofrece abrir la búsqueda OSM, sin introducir un proveedor público de geocodificación automático.
- Conversaciones: cards con preview, fecha y número de mensajes; búsqueda, orden, menú, abrir en chat, renombrar, destacar y eliminar con doble revisión. Mantiene el almacenamiento por cuenta.
- Google: pruebas controladas de Docs/Sheets/Slides y ocho subcarpetas Drive, con IDs guardados antes de las operaciones posteriores, lectura verificadora y protección frente a creación ambigua. CONNECTED requiere escritura verificada, no solamente OAuth disponible.
- Artefactos: siete identificadores de plantilla, portada/índice/headers/paginación, tablas simples, XLSX con datos numéricos explícitos, dashboard, fórmula, validación y gráficos; PPTX paginado sin truncar su texto. ChartAgent renderiza bar, line, area, pie/donut y scatter con datos proporcionados; se reutiliza en PDF, DOCX, XLSX y PPTX. No inventa cifras.
- Se eliminan los accesos muertos Voz/Motor de IA del menú lateral y los duplicados Archivos/Multimedia del panel contextual.

## Límites pendientes

- Las condiciones se conservan para revisión; no se afirma evaluación autónoma de cualquier condición escrita en lenguaje natural. La interpretación libre fuera de las acciones soportadas continúa dependiendo de los agentes existentes.
- `ZarUI` es común a todos los diálogos migrados; el ledger persistente se aplica al chat y al borrado de conversaciones. Otros módulos conservan sus mecanismos de idempotencia y aprobación existentes.
- Los siete tipos de informe comparten una estructura editorial; faltan diseños diferenciados completos, imágenes contextuales y todos los layouts avanzados de presentación. Los charts locales no implican una inserción automática verificada de imágenes en Google Docs/Slides.
- Las rutas del mapa se abren en Google Maps; no se dibuja una ruta calculada dentro de Leaflet. No se solicita permiso de ubicación nuevo.
- Canva permanece preparado para acción humana; no hay OAuth ni exportación Canva verificados. YouTube conserva canal pendiente y AdSense SIGNUP_REQUIRED.
- Ningún test mock demuestra conectividad real de Alpaca ni escritura Google. La verificación de producción se informa por separado, incluidos bloqueos reales de permisos/API/feed.

## Validación focalizada

- `tests/release-339.py`: planner, referencias, payload/owner, doble confirmación, idempotencia, eventos sin mensajes ficticios, bus privado, contrato OHLCV, conversaciones, gráficos, workbook y escrituras Workspace simuladas.
- `tests/release-339-ui.cjs`: escritorio/móvil, ausencia de diálogos nativos, ticks incrementales, conservación de inputs y Automaton, histórico único, doble modal, Leaflet real en DOM, búsqueda/acciones de conversaciones y muestras de layout de 50/500/3000 agentes sin solapamientos.
- `tests/stonks-rendering.cjs`: se conserva la regresión de escritorio y siete tamaños, estructura, chat, Position Management, Risk y cierre/reapertura; la comprobación de autosync ahora verifica el bus.
- `tests/release-338.py`, `tests/release-338-ui.cjs` y `tests/release-337.py`: regresiones previas conservadas y expectativa de versión actualizada donde corresponde.
