# ZAR v31.3.46 — Stonks Shadow Outcome Tracker

- Mide cada señal Shadow con barras IEX posteriores reales, sin crear órdenes.
- Horizontes: 5, 15 y 60 barras de 1 minuto posteriores a la señal.
- Calcula retorno direccional, MFE y MAE.
- El P/L hipotético solo se calcula para decisiones aprobadas por Risk y nunca se envía al broker.
- Outcome Tracker se actualiza como máximo aproximadamente una vez por minuto para ahorrar llamadas.
- Añade resumen visual y columnas de outcome al Diario Shadow.
- Añade el subagente `shadow_outcome` al orquestador financiero.
- Sigue siendo 0 órdenes en modo Shadow.
