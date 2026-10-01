# ZAR v32.0.3 — Stale Paper Owner Recovery

Hotfix de ownership para ZAR Stonks Paper.

- Si otro scope conserva ownership local, ZAR verifica primero la exposición real en Alpaca Paper.
- Con 0 posiciones y 0 órdenes abiertas, libera automáticamente el owner huérfano y permite transferir el motor.
- Si existe cualquier posición u orden Paper abierta, la transferencia sigue bloqueada y muestra los conteos.
- Si Alpaca no puede verificarse, falla de forma segura y no transfiere control.
- El worker global sigue un único `engine_owner.json`, por lo que la transferencia no crea un segundo motor.
- No modifica Risk, Quality Guard, sizing, lifecycle, Paper Execution ni el hard-lock de Live.
