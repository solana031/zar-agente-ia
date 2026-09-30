# ZAR v31.3.28 — Stonks Multi-Agent Phase 1

Primera fase de ZAR Stonks Multi-Agent, construida sobre v31.3.27 sin modificar la persistencia.

## Agentes
- Supervisor: coordina el ciclo.
- Market Data: reconcilia Alpaca Paper y reloj de mercado.
- Analysis: reutiliza el motor de señales técnicas existente.
- Risk: pre-check local; Decision/Risk del servidor sigue siendo la autoridad final.
- Paper Execution: ejecuta exclusivamente por la ruta Paper endurecida existente.
- Position Manager: reutiliza el lifecycle, ownership, SL/TP y reconciliación ya probados.

## Eficiencia
El routing y estos agentes son deterministas: 0 tokens de IA para coordinar un ciclo Stonks.
La IA podrá añadirse después como analista opcional, nunca como bypass de Risk/Execution.

## Persistencia
No se incluyen data/, users/, bases de datos, historiales ni estado Paper en el ZIP.
El estado persistente continúa bajo ZAR_DATA_DIR / volumen Railway.
