# ZAR v29.1.1 — UI / Buttons Fix

Corrección sobre ZAR v29.1.

## Corrección principal
- Se corrige un error de sintaxis JavaScript introducido en el código de voz Live.
- Ese error impedía que se ejecutara el script principal completo del frontend.
- Como consecuencia, los `onclick` de los botones podían mostrar el efecto visual del toque/click pero no ejecutar sus funciones.
- Se conserva íntegramente v29.1: Dictado Pro, Gemini 3.8 Live, TTS, archivos, memoria, Google, Studio y chat.

## Comprobación
- JavaScript principal validado con Node.js (`node --check`).
- Scripts adicionales validados sin errores.
