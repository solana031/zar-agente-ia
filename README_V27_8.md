# Zar V27.8 — Studio universal + audio creativo

## Novedades
- Editor de audio real dentro de Zar Studio, en escritorio y móvil.
- Creación de bases instrumentales desde cero de forma procedural: género, BPM, duración, energía e instrumentos.
- Panel por capas con batería, bajo/808, piano, guitarra, pluck, pad, cuerdas, bell, lead, órgano y metales.
- Previsualización de las bases generadas sin salir de Zar.
- Carga de voz y efectos creativos rápidos mediante FFmpeg (eco, robot, radio, deep, bright, wide, etc.). El modo Auto-Pitch se presenta como creativo/rápido, no como sustituto de un afinador profesional dedicado.
- Orden universal por texto y voz para el editor de imagen, vídeo y audio.
- Las órdenes de imagen incluyen mejora automática, nitidez base, ajustes de luz/color, filtros, transformaciones y texto con estilo/posición.
- Las órdenes de vídeo se ejecutan sobre el proyecto actual sin obligar a reconstruirlo desde cero.
- Nueva ruta `/health` se conserva.
- No se cambian las credenciales ni las variables existentes de Railway.

## Uso rápido
1. GitHub: sustituir archivos por esta versión y hacer Commit changes.
2. Railway: esperar a que el deployment termine y hacer `Ctrl+F5` en Zar.
3. Zar Studio → Audio → Nueva base.
4. Elige género/BPM/duración/instrumentos y pulsa `Generar base`.
5. O habla con Zar: `Haz una base de trap a 142 BPM durante 60 segundos y añade 808 y un lead más oscuro.`

## Nota
El render de audio se hace con síntesis procedural propia, sin incorporar canciones o samples de terceros. Los efectos de voz son transformaciones DSP/FFmpeg; la afinación profesional tipo Auto-Tune requiere procesamiento de pitch específico que se puede añadir en una fase posterior.
