# ZAR v31.3.13 — motor autónomo Paper de ZAR Stonks

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


## v31.3.13 — Motor autónomo Paper
- Añade un ejecutor servidor persistente cada 30 segundos.
- Funciona aunque la ventana de Stonks esté cerrada.
- Está desactivado por defecto y requiere activación explícita.
- Solo permite ejecución en `paper_auto` + modo Paper + motor no pausado/no revocado.
- Reutiliza la misma ruta de Decision + Risk endurecida del panel.
- Usa un lock de fichero para evitar que varios workers Gunicorn ejecuten ciclos duplicados.
- El motor se vincula a un único espacio de usuario de ZAR mientras usa las credenciales globales de Alpaca configuradas en Railway.
- Revocar desactiva también el motor autónomo.
- Live continúa completamente desconectado.
