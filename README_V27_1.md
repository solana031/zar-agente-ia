# Zar V27.1 — Editor Multimedia Inteligente

Base: V27 / V26.1.

## Qué añade

- Menú multimedia desplegable en escritorio y móvil, conservando la interfaz principal limpia.
- Editor no destructivo sobre el proyecto: el archivo original del usuario permanece en `/data/video_creator/media`; las ediciones son instrucciones guardadas en el proyecto.
- Edición por clip: recorte inicial/final, velocidad, zoom, giro, volteo, look/color y texto.
- Reordenación y eliminación del clip del proyecto sin borrar el original almacenado.
- Edición localizada en un tramo temporal de un clip para efectos ligeros como blanco y negro, desenfoque, contraste, brillo y tonos cálido/frío.
- Comandos naturales de texto y por voz dentro del editor. La voz usa el mismo reconocimiento del navegador que el chat, pero la orden se aplica directamente al proyecto activo.
- Biblioteca amplia de transiciones basada en los 58 modos `xfade` disponibles en el FFmpeg incluido: fundidos, barridos, wipes diagonales, slides, círculos, radiales, zoom, viento, slices, pixelizado, desenfoques y más.
- Optimización heurística para Shorts/TikTok/YouTube con formato vertical cuando procede, ritmo más rápido, movimiento y transiciones. No promete viralidad.
- Previsualización del render antes de publicar. Zar no publica automáticamente.
- Música instrumental original procedural, sin usar canciones o samples de terceros.

## Órdenes de ejemplo

- `quita el clip 3`
- `recorta los primeros 1,5 segundos del clip 2`
- `haz zoom 1,15x en el clip 1`
- `pon zoom in entre los clips 2 y 3`
- `entre 0 y 2 segundos del clip 4 pon blanco y negro`
- `añade el texto 1: MADRID 2026`
- `hazlo más viral para TikTok`

## Optimización de viralidad: alcance y límites

La versión no presenta una puntuación de viralidad como hecho objetivo. TikTok publica recursos de Creative Center, tendencias, Top Ads y recomendaciones creativas, mientras que YouTube identifica el tiempo de visualización y la retención como métricas clave. Zar usa esas señales públicas como marco para sugerir/automatizar cambios, pero la referencia definitiva debe ser la analítica real de la cuenta del usuario.

## Investigación usada para el diseño

- Adobe Premiere documenta una biblioteca moderna de transiciones con nuevas familias de impactos, barridos, blur, zoom, movimiento, formas y animación.
- DaVinci Resolve documenta más de 100 transiciones y más de 80 efectos acelerados, además de seguimiento y composición con Fusion.
- TikTok Creative Center ofrece tendencias, Top Ads, patrones creativos y datos para optimización.
- YouTube señala tiempo de visualización y retención de audiencia como métricas clave para Shorts.

## Seguridad

Ningún render de V27.1 se publica automáticamente. La previsualización y descarga están separadas de cualquier futura integración de publicación en YouTube/TikTok.
