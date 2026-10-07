# ZAR 33.4 — Resell candidate (local)

Primera implementación local de **ZAR Resell**. No conecta cuentas ni usa APIs privadas.

Incluye:
- entrada `♻️ ZAR Resell` en el menú;
- Comunidad con tarjetas Vinted/Wallapop (demo), título, precio y ubicación;
- Mis anuncios con favoritos, mensajes, ofertas y estado de gestión;
- Inbox de favorito y oferta recibida;
- flujos preparar oferta, aceptar, rechazar y contraofertar en **SIMULACIÓN LOCAL**;
- historial de decisiones;
- readiness de conectores Vinted/Wallapop como `NOT_CONFIGURED`;
- persistencia local en `ZAR_DATA_DIR/resell.json`.

## Seguridad
Ninguna acción del candidato llama a Vinted/Wallapop. Las acciones comerciales sólo se registran localmente para validar UX. Los conectores reales deberán declarar capacidades soportadas y exigir confirmación antes de cualquier acción externa.
