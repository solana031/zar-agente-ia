# ZAR v27.48 — VOZ PRO ANTIRUIDO

Corrección de v27.47 tras detectar duplicación de palabras cuando el micrófono recibe ruido de fondo.

## Cambios
- Preprocesado de audio en servidor antes de transcribir: mono 16 kHz, filtro paso alto/paso bajo y reducción moderada de ruido con FFmpeg.
- Usa `imageio-ffmpeg` ya presente en dependencias y mantiene fallback al audio original si la conversión no está disponible.
- Prompt de transcripción reforzado para ignorar ruido, música, TV, conversaciones ajenas, viento y artefactos de eco/micrófono.
- Si un artefacto produce repeticiones, Gemini debe conservar una sola aparición salvo que la repetición sea realmente pronunciada por el usuario.
- Se mantiene la transcripción literal: no resume ni responde a la petición.
- La interfaz indica que están activos el filtro anti-ruido y anti-eco.

## Objetivo de prueba
Con ruido de fondo, una frase como «¿Qué tiempo hace hoy en Madrid?» debe aparecer una sola vez, sin palabras espurias ni duplicaciones.
