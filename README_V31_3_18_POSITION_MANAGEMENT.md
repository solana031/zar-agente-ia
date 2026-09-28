# ZAR v31.3.18 — Paper Position Management

## Objetivo
Añade gestión de ciclo de vida para posiciones abiertas por el motor autónomo Paper de ZAR.

## Cambios
- Persistencia de `pending_entries` y `managed_positions`.
- Una compra enviada por ZAR se registra como entrada pendiente.
- Cuando Alpaca confirma la posición, ZAR guarda precio medio de entrada y niveles de stop/take.
- Gestión configurable y desactivada por defecto.
- Stop loss y take profit porcentuales, evaluados en servidor cada ciclo del motor.
- Solo se gestionan posiciones que ZAR abrió mediante su motor Paper; posiciones manuales quedan fuera.
- Las salidas usan órdenes Market Paper y se registran en auditoría.
- Se respetan PAUSA/REVOCAR y el límite máximo por operación.
- Nueva UI en Configuración Risk para activar/desactivar gestión y configurar SL/TP.
- Estado de posiciones gestionadas y última acción visible en la UI.

## Seguridad
- Paper únicamente.
- No se conecta a Live.
- La gestión está desactivada por defecto para no alterar el comportamiento actual hasta que se configure explícitamente.
