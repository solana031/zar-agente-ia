# ZAR v31.3.11 — RESTORE CONTROL / KILL SWITCH UX

## Cambios
- Corregido el flujo Revocar → Restaurar en ZAR Stonks.
- Cuando `revoked=true`, el botón superior deja de mostrar `Reanudar` y pasa a mostrar `↺ Restaurar`.
- Al restaurar se retira únicamente el bloqueo de revocación; el motor queda `Pausado` hasta que el usuario pulse `Reanudar` explícitamente.
- Añadido `POST /api/stonks/restore`.
- Restaurar usa el modal visual de ZAR, no `alert()` del navegador.
- Si ocurre un error en pausa/reanudación/restauración, se muestra también el modal de ZAR.
- Al revocar se oculta el botón Revocar para evitar acciones redundantes.
- Versión visual actualizada a v31.3.11.

## Prueba
1. Revocar → debe quedar `Revocado · modo seguro` y mostrar `Restaurar`.
2. Pulsar `Restaurar` → confirmar en modal ZAR → debe quedar `Pausado · modo seguro`.
3. Pulsar `Reanudar` → debe quedar `Activo · paper`.
4. No se envía ninguna orden en Restaurar.
