# ZAR v30.2.8 — Gmail UI profesional

- Los correos leídos por ZAR se muestran como tarjetas visuales estructuradas, con remitente, destinatario, asunto, fecha y cuerpo.
- Los resúmenes de Gmail se muestran con jerarquía visual y sin Markdown crudo.
- Los borradores muestran estado **BORRADOR · NO ENVIADO**, destinatario, asunto, cuerpo y acciones de Enviar/Cancelar.
- Se eliminan de la presentación los asteriscos, almohadillas y otros marcadores Markdown sueltos; el contenido se conserva.
- Los enlaces se muestran como enlaces clicables y el contenido se escapa antes de renderizarse.
- La respuesta por voz no lee el JSON interno de las tarjetas.
- Se mantiene la confirmación explícita antes de enviar correos.
- Se conserva toda la funcionalidad y persistencia de versiones anteriores; el paquete de release no incluye `data/`.
