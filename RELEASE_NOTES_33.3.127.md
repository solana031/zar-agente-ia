# ZAR 33.3.127

- Google: selección libre en CUENTAS, varias cuentas cifradas por propietario y conservación de autorizaciones anteriores.
- OAuth: retorno automático del navegador, alternativa en página principal si se bloquea el popup y recibos de un solo uso; se mantienen state, PKCE y CSRF.
- Android: evitar clasificar Version/4.0 como WebView sin el marcador explícito wv. Una WebView real conserva la protección contra login embebido y ya no ofrece el enlace que repetía la pantalla bloqueada.
- Móvil: aviso compacto y ajustes de CUENTAS, cabecera y pestañas compartidas.
- Verificación: pruebas OAuth con proveedores simulados, renderizado móvil y regresión de interfaz. La autorización real desde el móvil requiere selección y consentimiento de Google por el titular; no se afirma completada.
