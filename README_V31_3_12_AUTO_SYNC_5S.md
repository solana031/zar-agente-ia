# ZAR v31.3.12 — sincronización automática de ZAR Stonks

## Objetivo
El panel ZAR Stonks deja de depender de pulsar manualmente «Actualizar» en cada bloque.

## Cambios
- Sincronización automática cada 5 segundos mientras la ventana ZAR Stonks está abierta.
- Actualiza en paralelo:
  - estado ZAR Stonks (pausa/reanudar/revocar, modo y Risk);
  - cuenta Paper, equity, cash/buying power y posiciones;
  - órdenes Paper y sus estados;
  - auditoría reciente.
- Los botones manuales «Actualizar» se mantienen para una actualización inmediata.
- Los campos de Risk no se sobrescriben mientras el usuario está editándolos.
- La interfaz muestra `AUTO · 5 s` y cambia brevemente a `SYNC · …` durante cada sincronización.
- Al cerrar Stonks, el temporizador se detiene.
- El motor de señales conserva su propio ciclo de 30 segundos.
- No se habilita Live: las operaciones siguen siendo exclusivamente Paper y sujetas a pausa/revocación y Risk.

## Arquitectura
Esta versión usa polling desde el navegador cada 5 segundos sobre los endpoints ya existentes. No introduce WebSocket/SSE ni expone credenciales de Alpaca al navegador.

## Seguridad
- Live continúa desconectado.
- No se eliminan las confirmaciones manuales.
- No se eliminan los límites de Risk.
- Pausar/Revocar siguen bloqueando la ejecución.

## Verificación
- Sintaxis JavaScript validada con `node --check`.
- Sintaxis Python validada con `py_compile`.
