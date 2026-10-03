# ZAR v33.1.2 — Media DramaClaw Direct

## Objetivo
Eliminar el fallback local/negro en ZAR Media y usar DramaClaw como motor real de producción.

## Cambios clave
- `ZAR Media` pasa a `DIRECT_ONLY` por defecto (`ZAR_MEDIA_DIRECT_ONLY=1`).
- Si DramaClaw no está conectado, Media **no** genera ya el vídeo local de fallback.
- Se añade autodetección de endpoint a partir de `DRAMACLAW_API_URL` si no existe `DRAMACLAW_CREATE_URL`.
- Nuevo campo opcional `DRAMACLAW_WEB_URL` para abrir el editor web de DramaClaw desde ZAR.
- Nueva acción `Editar / regenerar` para reenviar instrucciones de edición a DramaClaw.
- La publicación sigue haciéndose desde ZAR sobre el vídeo final devuelto por DramaClaw.

## Variables de entorno recomendadas en Railway
- `DRAMACLAW_API_URL=https://TU-HOST-DRAMACLAW:8780`
- `DRAMACLAW_CREATE_URL=https://TU-HOST-DRAMACLAW:8780/api/projects/create` (si conoces el endpoint exacto)
- `DRAMACLAW_WEB_URL=https://TU-HOST-DRAMACLAW:8080`
- `DRAMACLAW_API_TOKEN=...` (si tu despliegue lo requiere)
- `ZAR_MEDIA_DIRECT_ONLY=1`

## Voz
ZAR mantiene el router:
1. `ELEVENLABS_API_KEY` + `ELEVENLABS_VOICE_ID`
2. `F5_TTS_API_URL`
3. Gemini TTS

## Flujo de prueba
1. Crear historia.
2. Ciclo ahora.
3. Producir último MP4.
4. Previsualizar vídeo o abrir editor DramaClaw.
5. Editar / regenerar si hace falta.
6. Publicar.
