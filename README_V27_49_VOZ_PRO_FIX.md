# ZAR v27.49 — Voz PRO: corrección de envío

Corrección sobre v27.48.

- Mantiene limpieza de audio, filtro anti-ruido y modo verbatim.
- Corrige la ruta de transcripción: Gemini se llama mediante su endpoint OpenAI-compatible `/chat/completions`.
- Envía el WAV limpio como `input_audio`, que es el formato documentado por Gemini para comprensión de audio.
- Mantiene el modelo configurado en ZAR (`ZAR_API_MODEL`).
- Mantiene el envío automático del texto transcrito a Zar cuando la transcripción termina correctamente.
