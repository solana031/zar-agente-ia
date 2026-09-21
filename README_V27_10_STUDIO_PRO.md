# ZAR v27.10 — Studio Pro Compact + Publicación

Cambios:
- Studio de vídeo reorganizado en menús desplegables para reducir el scroll.
- Escenario de previsualización visual compacto y persistente.
- Proyecto, edición con Zar, texto, medios, transiciones, optimización y render agrupados.
- Centro de publicación con confirmación explícita antes de publicar o programar.
- Cola persistente de publicaciones programadas en `data/video_creator/publications/queue.json`.
- Cancelación de publicaciones programadas.
- Publicación inmediata mantiene los flujos oficiales de YouTube, Instagram, TikTok, WhatsApp y email.

Nota: la publicación automática directa en cada plataforma requiere las credenciales/OAuth y APIs de cada servicio. La cola y la interfaz de confirmación están preparadas para integrar esos conectores sin cambiar el modelo de proyectos.
