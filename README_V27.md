# Zar V27 — Creador Multimedia

## Qué añade
V27 incorpora un menú desplegable unificado (el mismo concepto que el menú móvil, disponible también en escritorio) y un Creador de Vídeos.

### Creador de Vídeos
Permite:
1. Crear/abrir un proyecto.
2. Subir varias fotos y vídeos.
3. Elegir formato: YouTube 16:9, YouTube Shorts 9:16, TikTok 9:16 o cuadrado 1:1.
4. Ajustar duración de las fotos.
5. Elegir transición: disolución, fundido a negro o corte.
6. Generar una pista musical instrumental original y procedural según el estilo (cinemático, energético, chill, dramático o viaje).
7. Previsualizar el MP4 dentro de Zar.
8. Abrir la previsualización o descargar el MP4.

La música de V27 se sintetiza mediante osciladores y percusión generada en el servidor; no incorpora catálogos ni samples de terceros. La etiqueta «sin copyright» debe entenderse como «sin utilizar obras musicales de terceros en el proceso de generación»; cualquier publicación comercial debe hacerse respetando las reglas de la plataforma y las obligaciones legales aplicables.

## Railway
No hace falta añadir claves nuevas. Sí hace falta que Railway despliegue el commit de V27. Las carpetas del creador se guardan bajo `/data/video_creator`, por lo que el volumen persistente que ya tienes es el almacenamiento esperado.

### Límite de subida
Por defecto, el creador admite hasta 300 MB por archivo. Se puede ajustar con la variable `ZAR_VIDEO_MAX_UPLOAD_MB` en Railway.

### Publicación
V27 NO publica automáticamente en YouTube ni TikTok. La publicación directa queda deliberadamente separada de la previsualización y se añadirá cuando integremos los permisos/API correspondientes.
