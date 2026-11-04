# Conexiones de ZAR: móvil, navegador y aplicación instalada

Los botones de Google, YouTube, Instagram y TikTok utilizan el mismo flujo externo. El inicio permanece en el dominio desde el que se abre ZAR; el retorno del proveedor usa la URL canónica registrada. La ventana original consulta el resultado antes de verificar la cuenta, incluso si la autorización se completa en otro navegador.

Cancelar no transforma una autorización antigua en una conexión nueva. Los errores del servidor se muestran en el panel. Abrir CUENTAS no dispara comprobaciones de todos los proveedores; REVERIFICAR TODAS sigue disponible y continúa si una petición falla.

## Configuración de TikTok

Usar la app existente. Configurar en el servidor, nunca en el navegador:

- `TIKTOK_CLIENT_KEY` y `TIKTOK_CLIENT_SECRET`.
- `PUBLIC_BASE_URL`: origen HTTPS público, sin ruta.
- `TIKTOK_REDIRECT_URI`: exactamente `PUBLIC_BASE_URL/oauth/tiktok/callback`; si no se especifica se calcula esa URL.
- Registrar esa misma URL en Login Kit Web. Autorizar `user.info.basic` y `video.publish` en la app existente.

Después, pulsar CONECTAR o RECONECTAR y completar el consentimiento en TikTok. La comprobación de publicación conserva el requisito de la cuenta operacional existente y las opciones de privacidad devueltas por el proveedor. Conectar no publica vídeos.

Las credenciales se cifran en el directorio persistente `ZAR_DATA_DIR`, separadas por espacio de usuario. La renovación conserva el refresh token nuevo y comprueba que no cambie la identidad. Las publicaciones y las consultas de estado usan esa misma credencial. El token de entorno anterior queda como compatibilidad solo donde no exista una autorización guardada; un archivo corrupto o una renovación fallida no resucitan ese token anterior.

Shopify y Stripe conservan sus asistentes de acceso de servidor. Los bloqueos de Meta, revisiones de apps y permisos denegados requieren completarse con el proveedor; el diseño no oculta esos estados.

## Verificación

Pruebas de servidor: `tests/test_account_connections.py`, `tests/test_oauth_transport.py`, `tests/test_text_video_social.py`, `tests/test_tiktok_oauth.py`, `tests/test_instagram_token_lifecycle.py`.

Pruebas de navegador: `tests/oauth-launcher-ui.py`, con Playwright y `ZAR_TEST_BROWSER` opcional. Incluyen ventanas externas, retorno a la misma pestaña si se bloquean ventanas emergentes, panel embebido, WebView Android, cancelación, errores y anchos 320–1440 px. Generan capturas con datos simulados en `artifacts/connections/`.

Referencias oficiales: [Login Kit Web](https://developers.tiktok.com/docs/en/login-kit-web) y [gestión de acceso y renovación](https://developers.tiktok.com/docs/en/oauth-user-access-token-management).

Estas pruebas no autorizan cuentas reales ni demuestran la configuración del despliegue. Publicación autorizada como 33.3.128. No se modifican las variables de Railway.
