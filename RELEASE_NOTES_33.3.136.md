# ZAR 33.3.136

## ReposNews
- Cada artículo publicado tiene una portada propia. Los que usaban un logo o una imagen oficial la integran ahora como referencia dentro de su portada "cómo funciona". Las 45 portadas actuales son distintas entre sí.
- Portada de la web por páginas deslizables (12 guías cada una), con pestañas numeradas y flechas.
- Orden de la portada: más recientes, más vistos (contador propio), novedades, más estrellas en GitHub (se actualiza a diario) y más antiguos.

## Llamadas de ZAR gratuitas
- Web Push estándar implementado sin dependencias externas y validado con el ejemplo oficial del RFC 8291.
- Pantalla de llamada entrante: tono, voz de ZAR y respuesta con «sí»/«no» por voz o botones. Si un artículo está listo, puedes publicarlo desde la llamada.
- Se activa por dispositivo en Ajustes de avisos.

## Interfaz
- Botón «Inicio» en todas las pestañas, en CUENTAS y en las secciones abiertas directamente.
- Renovación visual (`zar-refresh.css`) de la barra lateral, la barra superior, las pestañas, el inicio, el chat, el panel derecho, los botones y los formularios. Se mantiene la misma paleta.
- CUENTAS: cuando falta configurar un proveedor (TikTok) se abre su asistente en lugar de un error genérico. `tests/accounts-ui.py` vuelve a pasar.

## Railway
- Añadidas `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY` y `WHATSAPP_VERIFY_TOKEN`.

## Validación
- 1118 pruebas Python, más las de navegador de Stonks (8 tamaños), notificaciones, CUENTAS, barra lateral, Sites y páginas públicas de ReposNews.
