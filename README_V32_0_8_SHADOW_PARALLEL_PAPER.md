# ZAR v32.0.8 — Shadow paralelo a Paper Auto

Hotfix focalizado de ZAR Stonks.

## Corrección
- Shadow deja de depender exclusivamente de `execution_mode=shadow`.
- En `paper_auto`, Shadow observa en paralelo cada ciclo autónomo.
- Shadow evalúa Decision + Risk siempre con `execute=False` y mantiene **0 autoridad de broker**.
- Una señal ya observada en la misma barra no se duplica cada ~5 s.
- Paper Auto continúa después de la observación Shadow por su ruta normal: Quality Guard → Decision/Risk → Alpaca Paper.
- Los contadores `shadow_cycle_total`, `shadow_last_cycle`, `shadow_last_reason` y outcomes avanzan también en Paper Auto.
- LIVE permanece bloqueado y no se ha modificado.

## Seguridad
Este cambio no modifica límites de Risk, sizing, credenciales, permisos LIVE ni ownership. Shadow nunca crea órdenes.
