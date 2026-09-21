# ZAR v29.0 — Core + Model Router + Control Center

Base: ZAR v27.53 SEND FIX.

## Cambios
- Nuevo registro centralizado de modelos en `app/model_router.py`.
- El cerebro conversacional queda en `gemini-3.8-flash` por defecto.
- Ruta separada para `gemini-3.5-transcribe`.
- Ruta separada para `gemini-3.8-live`.
- Ruta TTS separada.
- Rutas creativas separadas para imagen, vídeo y música.
- Ruta preparada para Deep Research y Gemini Embedding 2.
- Todos los modelos se pueden sobrescribir con variables `ZAR_*_MODEL` sin tocar el código.
- `/api/control/health` incorpora versión, configuración segura de IA y catálogo de modelos sin exponer claves.
- Nuevo acceso rápido **Control ZAR** en la pantalla principal para revisar modelos y servicios.
- Se conserva el flujo de envío de v27.53, memoria, Google, Studio, archivos, tareas y voz.
- No se vuelve a introducir el texto central «Hola, soy Zar».

## Variables opcionales
- `ZAR_REASONING_MODEL`
- `ZAR_DEEP_RESEARCH_MODEL`
- `ZAR_TRANSCRIBE_MODEL`
- `ZAR_LIVE_MODEL`
- `ZAR_TTS_MODEL`
- `ZAR_IMAGE_MODEL`
- `ZAR_IMAGE_PRO_MODEL`
- `ZAR_VIDEO_MODEL`
- `ZAR_VIDEO_FAST_MODEL`
- `ZAR_MUSIC_MODEL`
- `ZAR_EMBEDDING_MODEL`

Las claves API siguen siendo variables de entorno y no se incluyen en el repositorio.
