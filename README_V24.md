# Zar V24 — Google Contacts + Internet Search

V24 añade dos capacidades al agente:

1. **Google Contacts**: búsqueda y gestión de contactos mediante People API.
2. **Internet en tiempo real**: `web_search` usa Google Search grounding de Gemini para responder consultas actuales con fuentes/citas. `web_open` permite abrir una URL pública y extraer texto para análisis.

## Configuración Google Contacts
Habilita **People API** en el mismo proyecto de Google Cloud y conserva el scope de OAuth `https://www.googleapis.com/auth/contacts`. Después, usa **Reautorizar Google** una sola vez para ampliar la sesión si Zar indica que falta ese permiso.

## Configuración de Internet
No necesitas una API key de búsqueda separada. Zar usa la `GEMINI_API_KEY`/clave Gemini que ya utiliza para el motor API y la herramienta integrada de Google Search. Google documenta que la fundamentación con Google Search devuelve datos web actuales y metadatos de citas; los modelos Gemini 3.6+ admiten esta herramienta.

## Ejemplos
- “Busca en Internet qué ha pasado hoy con la empresa X.”
- “Busca opiniones sobre este producto y compáralas.”
- “¿Cuál es el precio actual de…?”
- “Mira esta web y dime de qué trata: https://…”

**Importante:** las búsquedas web pueden consumir cuota de Gemini API, pero no requieren una nueva API key de Maps ni nuevos permisos OAuth.
