# Social Publishing sobre VideoProject

El módulo existente `app/text_video_social.py` coordina los adapters existentes de
Instagram, TikTok y YouTube. No se crea otro OAuth. El panel de conexiones vive en
Identidad y cuentas y en el proyecto privado, nunca en Sites.

`POST /api/social/connections/readiness` utiliza las credenciales existentes y solo
consultas de identidad/estado. Exige sesión y business CSRF. Guarda observaciones
seguras y las acciones que faltan en el Human Action Center. No devuelve tokens.

- Instagram: cuenta exacta @zaragente031, identidad y permiso de publicación se
  verifican por separado. Un HTTP 401 sin subcódigo no se llama «token caducado».
  RECONECTAR reutiliza `/api/reposnews/instagram/connect?publishing=1`, añade solo
  `instagram_business_content_publish` a los permisos de la integración existente,
  y vuelve al proyecto con revalidación. Un permiso solicitado no prueba su concesión.
- TikTok: el connector existente utiliza TIKTOK_ACCESS_TOKEN de Railway; no existe
  una ruta OAuth de TikTok en ZAR. CONECTAR lleva a la app existente del proveedor.
  Se debe autorizar `video.publish` para Direct Post y comprobar la identidad
  operacional. `creator_info/query` es una consulta de estado aunque usa POST.
  `scope_not_authorized` / `unaudited_client` => PERMISSION_REQUIRED. No se declara
  revisión aprobada ni canal listo por tener un token o una sesión web.
- YouTube: reutiliza Google OAuth con `service=youtube` y los permisos readonly /
  upload existentes. Comprueba el correo del token usado (zaragente031@gmail.com),
  consulta channels.list(mine=true), conserva ID/título reales y comprueba upload.
  No hay una API Shorts distinta. Sin canal: CHANNEL_REQUIRED.

El dry-run del proyecto usa FFprobe sobre el MP4 existente: tamaño, duración,
resolución, codec y audio. Devuelve SUPPORTED / NEEDS_TRANSCODE / INVALID; una
conexión bloqueada añade AUTH_REQUIRED al preflight. No regenera el vídeo ni sube
archivos. El actual perfil conservador requiere H264/AAC, 1080×1920, <=180 segundos
y <=80 MiB. No necesita transcode el WorldMonitor existente. La programación se
rechaza explícitamente porque los tres adapters no tienen un contrato común para ella.

La preparación firma revisión, hash del MP4, selección y metadatos. Cambiar el texto,
vídeo o destinos exige otro dry-run y otra confirmación. El único modal final crea
approval_id, APPROVED_BY_USER, video_revision_id, selected_platforms, approved_at
y approved_by_user. La cola y el commit de Instagram vuelven a comprobar el gate.

Idempotencia: proyecto + revisión + plataforma. REQUESTED sin respuesta => UNKNOWN,
nunca reenvío automático. Los resultados aceptados se conservan; solo BLOCKED o
FAILED pueden prepararse otra vez, seleccionando exclusivamente esa red y revisando
una nueva confirmación. Se mantiene historial, contador de intentos y aprobación.
La campana muestra los resultados y URLs, con enlaces de revisión para reintentos.

WorldMonitor 967c8d5fba064242 se conserva READY_PRIVATE. Esta entrega no autoriza
subirlo. Hace falta la aprobación explícita de Pablo antes de cualquier prueba real.

Referencias oficiales consultadas:
- https://developers.tiktok.com/docs/en/content-posting-api-reference-query-creator-info
- https://developers.google.com/youtube/data/reference/rest/v3/channels/list
- https://www.postman.com/meta/instagram/folder/1z5vxzu/instagram-api-with-instagram-login
