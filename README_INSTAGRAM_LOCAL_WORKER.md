# ZAR local Instagram worker

Railway orquesta; el PC obtiene el vídeo. No hay login de Instagram en Railway.
El worker solo acepta `FETCH_INSTAGRAM_REEL`, con URLs HTTPS de instagram.com
`/reel/<id>/` o `/p/<id>/`. No hay listener local ni shell remoto.

## Instalación local (Windows, Python 3.12)

Crear `.local/instagram-runtime` con `python -m venv` e instalar
`requirements-instagram-worker.txt` en ese entorno. Instalar Chromium con
`python -m playwright install chromium`, estableciendo `PLAYWRIGHT_BROWSERS_PATH`
en la ruta absoluta `.local/instagram-worker/browsers` del repositorio.
Las dependencias y el navegador del worker no se despliegan en Railway.

En ReposNews Inbox, «Conectar worker local» descarga una configuración con un
token exclusivo. Guardarla como `.local/instagram-worker/config.json`.
Crear una configuración nueva revoca el token anterior. El servidor conserva
únicamente su hash cifrado. No compartir el archivo ni incorporarlo a Git.

Ejecutar `scripts/zar-local-worker.ps1 -Login`. Iniciar sesión personalmente como
**@zaragente031**, con password/2FA/challenge directamente en Instagram.
El navegador visible usa exclusivamente `ZAR Instagram Browser Profile` dentro
de `.local/instagram-worker`. No importa perfiles ni cookies del Chrome personal.
La ventana se cierra al verificar la identidad y persiste el perfil local.

Ejecutar `scripts/zar-local-worker.ps1` para mantener el worker en marcha;
`-Once` ejecuta una consulta y un trabajo como máximo. Cerrar el proceso o apagar
el PC deja el worker OFFLINE. `scripts/install-instagram-worker-autostart.ps1`
instala la tarea de Windows **ZAR Local Instagram Worker**, que arranca al iniciar
sesión del usuario. El supervisor reinicia el proceso si termina, sin Codex,
contraseñas guardadas ni privilegios de administrador. El PC debe estar encendido
y con la sesión de Windows abierta; los trabajos esperan de forma persistente
cuando está apagado.

## Flujo y límites

El worker valida la identidad mediante el DOM público de Instagram. Primero
intenta yt-dlp público. Si no obtiene vídeo, abre el Reel con Playwright y la
sesión ZAR, observa sus respuestas de media y prueba yt-dlp con un cookie jar
temporal exclusivo, Instaloader y gallery-dl, en ese orden. No automatiza password,
CAPTCHA, fingerprint, evasión de límites ni llamadas privadas implementadas a mano.

Acepta MP4 de hasta 25 MiB y 180 segundos, validado con FFmpeg. Los fallbacks
tienen timeouts. El trabajo local completo tiene un límite de cinco minutos y un
lock impide arrancar dos workers simultáneos en el mismo perfil. Las descargas
directas exigen HTTPS/CDN de Instagram o Facebook, direcciones públicas y ausencia
de redirecciones. La subida lleva un token
de worker más una reserva temporal del trabajo; se comprueba tamaño, tipo y
duración en servidor. El contenido se procesa como evidencia no fiable.

Whisper CPU extrae la transcripción de PCM local; RapidOCR extrae texto de ocho
frames si Tesseract no está disponible. El modelo Whisper se descarga al primer
uso, por lo que conviene instalarlo antes del primer lote. El análisis cloud
puede enriquecer el resultado; si falla, permanecen transcript/OCR/caption.
Sin evidencia suficiente, se conserva NEEDS_DISAMBIGUATION y no se inventa
una entidad. Los extractores no garantizan acceso a cualquier Reel.

La cola recupera los mismos elementos PERMALINK_ONLY/NEEDS_DISAMBIGUATION y
fallos previos; preserva ID, remitente, fecha y artículos existentes. Las
reservas caducan tras 10 minutos; SESSION_EXPIRED requiere login manual local.
El stop global impide entregar/aceptar trabajos. Las fuentes oficiales, la
creación ES/EN, SEO y READY privado continúan en el pipeline editorial existente.
El worker nunca publica artículos. Los temporales y cookies de cada trabajo
se eliminan al terminar; solo el perfil y los modelos permanecen en el PC.

Referencias: [Playwright](https://playwright.dev/python/docs/auth),
[yt-dlp](https://github.com/yt-dlp/yt-dlp),
[Instaloader](https://instaloader.github.io/as-module.html),
[gallery-dl](https://github.com/mikf/gallery-dl).

## Borrador y decisión del titular

Cada Reel conserva su trabajo y deduplica el identificador del mensaje y su
permalink normalizado. El pipeline verifica fuentes oficiales de repositorios o
servicios sin exigir GitHub, genera y revisa artículos originales ES/EN, prepara
SEO y conserva provenance de los assets. Los frames permanecen privados para
revisión; usar uno como portada requiere seleccionarlo expresamente.

Solo un artículo completo puede alcanzar `READY_PRIVATE`. Fallos de generación
conservan análisis e investigación y se reintentan con espera y presupuesto
limitado, usando proveedores ya configurados. No se sustituye un artículo por una
nota genérica. Si se agotan los intentos se muestra el fallo; si falta realmente
la identidad se pide únicamente el nombre del proyecto.

El Notification Center y Human Action Center muestran título, proyecto, Reel,
imagen, previews ES/EN, fuentes, SEO y las acciones PUBLICAR, MODIFICAR y CANCELAR.
PUBLICAR es la única aprobación: una sesión autenticada y CSRF válidos vinculan
la decisión a la revisión concreta. `approval_status == APPROVED_BY_USER` y el
hash del contenido son obligatorios incluso en los endpoints anteriores. Un
worker, `confirmed: true` o `READY_PRIVATE` no conceden autorización.

MODIFICAR permite editar texto o guardar una petición natural y cambiar imagen
o portada. ZAR vuelve a preparar el borrador y solicita una aprobación nueva.
CANCELAR conserva borrador e historial. El contenido privado no cambia el sitio
público; solo PUBLICAR crea las páginas ES/EN y las incorpora al sitemap y a las
relaciones del sitio existente.
