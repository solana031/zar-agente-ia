# ZAR v29.1 — Voz 2.0

- Dictado Pro separado del cerebro conversacional: Gemini 3.5 Transcribe.
- Lectura de respuestas con Gemini 3.1 Flash TTS, con fallback al TTS del navegador si el servicio no está disponible.
- Conversación Live opcional con Gemini 3.8 Live mediante WebSocket y token efímero generado por el backend.
- El navegador nunca recibe la API key permanente de Gemini.
- Live envía audio PCM mono 16 kHz y reproduce audio PCM 24 kHz.
- Conserva v29.0.2: archivos, memoria, Control ZAR, Google, Studio y envío.
