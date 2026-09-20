# ZAR — Agente personal IA

Versión de referencia: **29.3.4**

Este repositorio contiene la versión web consolidada de ZAR. La base mantiene las funciones incorporadas hasta v29.3.4 y los arreglos recientes de interfaz y fiabilidad de botones.

## Funciones incluidas

- Chat con contexto persistente, conversaciones archivadas y memoria.
- Memoria e indexación local de información y archivos.
- Gestión de archivos, análisis y recuperación desde almacenamiento persistente.
- Google: autenticación OAuth y conexión con Gmail, Calendar, Drive, Docs, Sheets, Slides, Forms, Contactos y Tareas según los permisos autorizados.
- Copia local de datos autorizados de Google y estado de conexión.
- Búsqueda web y Deep Research.
- Google Maps.
- Voz: transcripción, limpieza de audio de entrada y lectura de respuestas.
- Selector de motor de IA, incluyendo Gemini y soporte para proveedor local/Ollama.
- Multimedia: YouTube, Spotify, creador/editor de vídeo y estudio de audio.
- Edición de imágenes y comandos de edición por texto/voz.
- Publicación de vídeo con flujo oficial de YouTube y cola de publicaciones.
- Centro de control y estado de salud de ZAR.
- Interfaz responsive para escritorio y móvil.
- Correcciones de navegación, botones, compositor inferior y límites visuales del hover.

## Estructura

- `app/` — aplicación Flask y módulos de ZAR.
- `app/templates/index.html` — interfaz web principal.
- `app/static/` — iconos, marca y recursos estáticos.
- `.github/workflows/prepare-zar-release.yml` — validación y empaquetado automático.
- `requirements.txt` — dependencias de producción.
- `Procfile` — arranque para Railway/Gunicorn.
- `config.example.json` — ejemplo de configuración local sin credenciales.

## Variables de entorno

Las credenciales y secretos deben configurarse en Railway (o en el entorno de ejecución), nunca en GitHub. El `.gitignore` excluye `credentials.json`, tokens OAuth, `config.json` y datos persistentes.

Entre las variables usadas por ZAR pueden encontrarse las de Gemini/IA, Google OAuth, YouTube OAuth, `PUBLIC_BASE_URL`, `GOOGLE_REDIRECT_URI`, `ZAR_SESSION_SECRET` y las variables de configuración de almacenamiento/servicios. Mantén las variables que ya funcionan en Railway al desplegar esta versión.

## Despliegue en GitHub + Railway

1. Crea un repositorio limpio.
2. Sube el **contenido descomprimido** de este ZIP en la raíz del repositorio. No subas el ZIP como un archivo dentro del repositorio.
3. Comprueba que `.github/workflows/prepare-zar-release.yml` exista en la rama principal.
4. En GitHub entra en `Actions` y ejecuta **ZAR Web — Validate and Package** con `Run workflow`.
5. El workflow valida Python, HTML/JavaScript, estructura y versiones, y genera un artefacto ZIP.
6. En Railway, despliega el repositorio/commit de GitHub manteniendo las variables de entorno y el volumen persistente `/data` que ya utiliza ZAR.

## Importante

No subas credenciales, tokens ni secretos al repositorio. Para actualizar ZAR, parte siempre de la última versión consolidada y sustituye los archivos de la aplicación; el workflow no cambia con cada número de versión.
