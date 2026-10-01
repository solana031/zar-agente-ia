# ZAR v31.3.51 — Autonomous Paper Learning

Release incremental sobre 31.3.50. No activa Live ni modifica credenciales/Railway.

## Stonks

- Mantiene el motor autónomo Paper en servidor y la autoridad final de Decision + Risk.
- Los WebSocket de mercado solo se abren en el proceso que posee `engine.lock`; los demás workers sirven el último snapshot persistido y no duplican streams.
- Añade `Paper Learning`, determinista y persistente en `ZAR_DATA_DIR`.
- El aprendizaje ingiere únicamente posiciones ZAR Paper cerradas y reconciliadas con fills del broker.
- Journal por operación: estrategia, símbolo, timeframe, señal/barra, indicadores, régimen, sentimiento público resumido, entrada/salida, P/L, retorno, duración, MFE/MAE y motivo de salida.
- Estadísticas por estrategia/símbolo/timeframe/régimen: muestra, win rate, expectancy, profit factor, P/L, drawdown, rachas, MFE/MAE y score descriptivo.
- Una muestra inferior a 20 operaciones no puede influir en prioridad. El learning nunca tiene autoridad sobre límites Risk, permisos, tamaño, Paper/Live ni kill switches.
- Se añade `paper_learning` al orquestador y un panel `STONKS LEARNING · PAPER` en Configuración Risk.
- Al seleccionar Paper automático desde la UI se activa también el selector de Position Lifecycle antes de guardar, para evitar armar un motor sin gestión de salida.

## Seguridad

- Shadow sigue sin autoridad de órdenes.
- Live continúa desconectado.
- Pausa, Revocación, Risk, ownership, deduplicación, market clock y Position Lifecycle siguen siendo obligatorios.
- Los tests no envían órdenes ni usan credenciales reales.

## Validación local

- 56 tests deterministas relevantes PASS.
- Test multiproceso de stream owner/non-owner PASS.
- Adaptive Orchestration Layout PASS.
- 19 scripts inline de `index.html` pasan `node --check`.
- `python -m compileall -q app` PASS.
- Playwright no está instalado en este contenedor, por lo que las regresiones de navegador no se reejecutaron aquí; 31.3.50 ya había pasado la revisión focalizada de Codex y esta release no rediseña la UI general.
