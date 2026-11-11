# ZAR 33.3.134

## ReposNews · portadas únicas
- Se sustituye la ilustración genérica "</>" por una portada propia para cada artículo que explica **cómo funciona** el proyecto: nombre, qué hace y 3-4 pasos (entrada → proceso → resultado) con iconos.
- Los 35 artículos publicados que tenían la portada genérica reciben una ficha de portada revisada (`app/static/reposnews/cover-specs.json`). Las portadas oficiales y las imágenes reales se conservan.
- Los artículos nuevos obtienen su ficha a partir del artículo y del análisis del reel (transcripción, resumen visual) con el modelo de texto configurado. Si no hay proveedor disponible, se usa una ficha determinista basada en el tema, que también es distinta para cada artículo.
- La ficha es un metadato de presentación: no cambia la revisión editorial ni reabre aprobaciones.

## Instagram · procesamiento autónomo
- La conversación autorizada se revisa cada 20 minutos de forma incremental (antes, una vez al día). Solo se notifica cuando cambia el número de reels.
- Si el worker local del PC está desconectado, el reel ya no se queda esperando: tras 15 minutos continúa en el servidor (media oficial, metadatos públicos y navegador del servidor).
- Con el piloto automático activo, los reels **antiguos** de la conversación también se publican. El historial se publica de forma escalonada (uno cada 20 minutos); los reels nuevos, al momento.
- Si el titular edita, cancela o pide cambios en un artículo, este queda retenido y no se republica automáticamente.

## ZAR Sites · nuevo panel
- Panel ReposNews con pestañas: Resumen, Artículos, Instagram, Mesa editorial, AdSense y legal, y Herramientas.
- Indicadores claros, estado del piloto automático con sus bloqueos explicados, estado de Instagram y botones "Revisar conversación ahora" y "Procesar y publicar reels antiguos".
- Cuadrícula de artículos con portada, filtros y búsqueda. Editar y Publicar reutilizan los flujos confirmados existentes.
- Los paneles técnicos anteriores siguen disponibles en sus pestañas.
- Se elimina un texto `\n` suelto visible al pie de la página.

## Validación
- Pruebas ReposNews, Instagram, historial, piloto automático y portadas: todas en verde excepto `test_recovery_116::test_health_bypasses_storage_network_session_and_blocked_later_hooks`, que ya fallaba en 33.3.133.
- Panel de Sites revisado en navegador a 1440 px y 390 px con datos locales simulados, sin errores de JavaScript ni desbordamiento horizontal.
- No se han hecho llamadas reales a Meta, Google ni proveedores de imagen.
