# ZAR 33.3.128

- Reconexiones de Google, YouTube e Instagram con inicio en el dominio de la sesión actual, CSRF actualizado y confirmación del servidor antes de reverificar.
- Cancelación y errores visibles sin indicar un éxito basado en credenciales antiguas; recuperación al volver a la pestaña.
- TikTok: autorización web, almacenamiento cifrado por espacio y renovación; la app existente necesita Login Kit y claves de servidor configuradas.
- Tarjetas de CUENTAS adaptadas a móvil y escritorio, paleta conservada, botones accesibles y controles existentes disponibles.
- Abrir CUENTAS no bloquea sus botones comprobando todos los proveedores; la revisión completa continúa aunque falle una petición.
- Pequeño pulido visual de paneles; sin cambios en lógica ni permisos de trading.

Validación: pruebas de cuentas, transporte OAuth, publicación social simulada, ciclo de tokens, flujos de Chrome y regresión de interfaz Stonks. La validación con proveedores simulados no demuestra que Meta/TikTok hayan aprobado los permisos de las cuentas reales.

Configuración y procedimiento: `docs/CONNECTIONS_RECONNECT.md`.
