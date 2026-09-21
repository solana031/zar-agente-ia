# ZAR v27.39 — Robust live web search

## Cambios
- Google Search grounding sigue siendo el proveedor principal.
- Si Gemini devuelve cuota/rate-limit/5xx o no devuelve metadatos de grounding, Zar usa un fallback de búsqueda web en vivo.
- Fallback estructurado opcional con `BRAVE_SEARCH_API_KEY` si está configurada.
- Fallback sin clave mediante DuckDuckGo HTML y Bing RSS.
- Las respuestas de búsqueda incluyen `live=true`, proveedor y fuentes.
- Regla estricta: si no existe evidencia de búsqueda en vivo, Zar no debe afirmar que ha buscado en Internet.
- Las peticiones explícitas del tipo «busca en Internet» se someten a una preconsulta web determinista antes de la respuesta del modelo.
- Si la búsqueda falla, Zar debe informar de que no pudo verificar la información en Internet en lugar de rellenar con conocimiento interno.

## Railway
No requiere una variable nueva para funcionar. `BRAVE_SEARCH_API_KEY` es opcional y permite añadir un proveedor estructurado adicional sin sustituir Google Search.
