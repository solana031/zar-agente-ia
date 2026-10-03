# ZAR 33.1.1 · Media Direct

- Conserva el briefing completo como `master_brief`.
- DramaClaw Direct es el proveedor preferido cuando `DRAMACLAW_CREATE_URL` está configurado.
- ZAR Native Visual genera escenas 9:16 con Gemini Image; Wikimedia Commons y gráfico son fallbacks sucesivos.
- Voice Router: ElevenLabs → F5-TTS remoto → Gemini.
- ElevenLabs admite stability/similarity/style/speaker boost por variables de entorno.
- Media muestra motor visual, voz, escenas y tamaño del briefing realmente usados.
- Las URLs absolutas devueltas por DramaClaw se previsualizan sin prefijar el host de ZAR.
- TikTok/Reels continúan detrás de confirmación.
- Stonks no cambia.

## Variables opcionales

DramaClaw Direct: `DRAMACLAW_CREATE_URL`, opcional `DRAMACLAW_API_TOKEN`, `DRAMACLAW_API_URL`.

ElevenLabs: `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, opcionales `ELEVENLABS_MODEL_ID`, `ELEVENLABS_STABILITY`, `ELEVENLABS_SIMILARITY`, `ELEVENLABS_STYLE`, `ELEVENLABS_SPEAKER_BOOST`.

F5-TTS: `F5_TTS_API_URL`, opcional `F5_TTS_API_TOKEN`, `F5_TTS_REFERENCE_AUDIO`, `F5_TTS_REFERENCE_TEXT`, `F5_TTS_SPEED`.
