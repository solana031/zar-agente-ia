# ZAR v27.47 — VOZ PRO

Evolución de v27.46 centrada en entrada de voz web.

## Cambios
- Captura de micrófono con `getUserMedia` usando `echoCancellation`, `noiseSuppression`, `autoGainControl`, mono y 48 kHz cuando el navegador lo admite.
- Cadena Web Audio para limpieza adicional: filtro paso alto, paso bajo y compresor dinámico.
- Detección básica de voz/silencio para cerrar automáticamente la grabación tras una pausa.
- Grabación en WebM/Opus y envío al backend para transcripción literal con Gemini.
- Prompt de transcripción orientado a conservar nombres, números, marcas, comandos y palabras pronunciadas sin resumir ni reinterpretar.
- Fallback al reconocimiento `SpeechRecognition` del navegador si el modo PRO no está disponible.
- Nuevo endpoint `/api/voice/transcribe`.

## Nota
La transcripción literal no puede garantizar coincidencia perfecta cuando el audio es realmente inaudible o ambiguo. El sistema evita deliberadamente que el modelo responda o reformule el contenido y pide marcar las partes inaudibles en vez de inventarlas.
