# Avisos de ZAR fuera de la app (email, WhatsApp, llamadas)

## Email (activo)
- Remitente: la cuenta Google **zaragente031@gmail.com** conectada en CUENTAS (permiso Gmail ya concedido).
- Destinatario por defecto: solana031@gmail.com (se cambia en Notificaciones → Ajustes).
- Si el Gmail de ZAR no está conectado, el aviso queda pendiente, se reintenta y aparece una notificación en ZAR.

## Qué se envía
- **Resumen semanal** (lunes 09:00, Madrid): visitas a reposnews.com (contador propio, anónimo y sin cookies),
  clics/impresiones de Google (Search Console), artículos publicados, reels procesados, YouTube, TikTok y AdSense.
- **Avisos importantes al momento**: publicaciones fallidas, cuentas a reconectar, artículos listos,
  reels que necesitan identificación, errores del sistema.
- **Avisos a medida** pedidos en el chat o por WhatsApp:
  - «notifícame de las visitas de ReposNews cada lunes a las 10»
  - «avísame por whatsapp del precio del bitcoin cada 6 horas» (temas libres: ZAR busca en la web y resume)
  - «recuérdame revisar AdSense cada viernes»
  - «qué avisos tengo» · «deja de notificarme de youtube»

## Datos de YouTube y TikTok
- YouTube: estadísticas del canal con el permiso actual. Para visualizaciones semanales e **ingresos estimados**,
  reconecta YouTube en CUENTAS (ZAR pide ahora `yt-analytics.readonly` y `yt-analytics-monetary.readonly`).
- TikTok: seguidores, «me gusta» y vídeos requieren el permiso `user.info.stats` aprobado en la app de TikTok.
  TikTok no ofrece ingresos estimados por API.

## WhatsApp (WhatsApp Business Cloud API de Meta)
Variables en Railway (servicio web):
- `WHATSAPP_TOKEN`: token permanente de un usuario del sistema con `whatsapp_business_messaging`.
- `WHATSAPP_PHONE_NUMBER_ID`: ID del número emisor de WhatsApp Business.
- `WHATSAPP_APP_SECRET`: secreto de la app de Meta (firma de los webhooks).
- `WHATSAPP_VERIFY_TOKEN`: texto aleatorio que también se escribe en Meta al registrar el webhook.
- Opcional `WHATSAPP_TEMPLATE_NAME` y `WHATSAPP_TEMPLATE_LANG` (por defecto `es`): plantilla aprobada con una variable
  en el cuerpo, para escribirte cuando hayan pasado más de 24 h desde tu último mensaje (regla de Meta).

Webhook en Meta: `https://<dominio de ZAR>/api/whatsapp/webhook`, campo `messages`.
Solo se aceptan mensajes firmados y del número configurado en Ajustes. Desde WhatsApp puedes pedir avisos,
consultar los activos y publicar un artículo listo con el botón «Publicar» (ligado a la revisión exacta del borrador).

## Llamadas (preparado, desactivado)
Variables `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` y `TWILIO_FROM_NUMBER`. Cuando existan, «Llamada» se puede
marcar como canal de avisos importantes y ZAR leerá el aviso por voz.
