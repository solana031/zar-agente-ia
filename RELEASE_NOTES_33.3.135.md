# ZAR 33.3.135

## Instagram: PC de ZAR + Railway
- El worker de Instagram es el del PC con Windows donde está ZAR (no el Mac). `arrancar_zar.bat` lo inicia en segundo plano si está configurado.
- Si el PC no está disponible, Railway continúa solo tras 15 minutos.

## Notificaciones
- Desplegable rediseñado: filas compactas agrupadas por día, icono y color por tipo, una sola fila de filtros, acciones visibles solo cuando hacen falta, «Mostrar más» y marcar como leída al abrir.
- Nueva vista **Ajustes de avisos**: email, avisos importantes, WhatsApp, llamadas y avisos periódicos.

## Avisos por email, WhatsApp y llamadas
- Email desde zaragente031@gmail.com a solana031@gmail.com: resumen semanal, avisos importantes al momento y avisos a medida pedidos en el chat («notifícame de X cada …»).
- Contador propio de visitas de reposnews.com: anónimo, sin cookies y excluyendo bots.
- WhatsApp Business Cloud API: avisos, comandos y botón «Publicar» para artículos listos, con webhook firmado y solo desde tu número. Queda activo cuando se configuren las variables de Meta.
- Llamadas con Twilio preparadas (desactivadas hasta configurarlas).
- Guía: `docs/NOTIFICACIONES.md`.

## Cuentas
- Selector de cuenta activa para YouTube, TikTok e Instagram: cada cuenta verificada se guarda cifrada en este ZAR y se puede alternar sin volver a iniciar sesión.
- Google y AdSense usan el selector de Google.
- «Añadir otra cuenta» abre el inicio de sesión del proveedor.

## Revisión de errores
- `/health` y su prueba estaban desalineados; se corrige la prueba (`ok` lo usa el verificador de despliegue).
- Se quita un texto `\n` visible al pie de la página principal.
- En producción, los únicos 5xx de la semana coinciden con los reinicios por despliegue (1–2 minutos con un solo contenedor y volumen). No hay errores de código.
- Pendiente: `tests/accounts-ui.py` espera un diálogo antiguo de TikTok; ya fallaba en 33.3.133.

## Validación
- 1112 pruebas Python en verde, más las de navegador de Stonks, notificaciones y Sites.
