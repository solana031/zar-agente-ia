# ZAR v31.3.42 — STONKS VALIDATION LAB

- Backtester separado en un módulo determinista, sin LLM y testeable sin Flask.
- Corrige look-ahead del sizing: ATR de la barra cerrada previa.
- El riesgo por operación ahora dimensiona contra un stop 2×ATR que sí se aplica en la simulación.
- Señales al cierre y ejecución en la apertura siguiente.
- Métricas nuevas: CAGR, Sharpe, Calmar, expectancy, media de ganancias/pérdidas, exposición, duración, racha de pérdidas, benchmark y diferencia vs buy&hold.
- Stress test de slippage 1x/2x/3x.
- Diagnósticos de muestra pequeña e histórico corto.
- No crea órdenes ni modifica Paper state.
