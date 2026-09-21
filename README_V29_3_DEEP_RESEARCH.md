# ZAR v29.3 — Deep Research + Research Router

ZAR v29.3 añade una ruta de investigación profunda separada del cerebro conversacional normal.

## Qué incorpora

- Router de intención para detectar peticiones que realmente requieren investigación multi-paso.
- Gemini Deep Research mediante la Interactions API.
- Ejecución en segundo plano y espera/polling en el job de ZAR para investigaciones largas.
- Búsqueda web y contexto de URLs disponibles para Deep Research.
- Informes en español con instrucciones para contrastar fuentes, distinguir hechos/opiniones y citar las fuentes importantes.
- Archivo persistente por usuario en `/data/users/<usuario>/research`.
- Panel de Investigaciones para consultar informes guardados.
- Nuevos accesos rápidos de Investigación en la interfaz web/móvil y paleta de comandos.
- Conserva las rutas deterministas de Gmail, Calendar, Workspace, multimedia y recordatorios antes de activar Deep Research.
- Mantiene Memory 3.0, voz, Live, TTS, archivos, Google, Studio y el resto de v29.2.3.

## Uso

En el chat se puede pedir, por ejemplo:

> Haz una investigación profunda sobre el mercado de restaurantes de Majadahonda, compara competidores, precios, conceptos y tendencias y cita las fuentes.

Las peticiones sencillas siguen usando el cerebro normal o la búsqueda web normal. Deep Research se reserva para trabajos multi-fuente y multi-paso.

## API interna

- `POST /api/research/start`
- `GET /api/research/<interaction_id>`
- `GET /api/research/archive`
- `GET /api/research/archive/<report_id>`

La API key de Gemini permanece en el servidor; nunca se envía al navegador.
