# ZAR v32.0.0 — Stonks Paper Profitability

Release Paper-only orientada a mejorar disciplina operativa, trazabilidad de consumo IA y aprendizaje de Stonks sin habilitar Live.

## Cambios principales

- Telemetría explícita de Stonks: llamadas GPT, Gemini, modelo local y coste API estimado.
- AI Gate continúa cerrado por defecto y el ciclo normal sigue diseñado para 0 tokens.
- Nuevo `Paper Quality Guard` determinista antes de la ruta Decision + Risk:
  - puntuación descriptiva de calidad de señal;
  - filtro de volatilidad/extensión extrema;
  - cooldown por símbolo;
  - límite de reentradas Paper por símbolo/día;
  - Learning maduro (mínimo 20 operaciones) puede ajustar prioridad de forma acotada;
  - nunca modifica sizing, límites Risk, SL/TP, permisos o modo Paper/Live.
- Nuevo subagente `paper_quality` dentro del orquestador.
- Los SELL autónomos sobre símbolos sin posición no se convierten en nuevas posiciones cortas; el filtro de nuevas entradas está limitado a BUY y las salidas existentes siguen pasando por lifecycle/Decision/Risk.
- Estadísticas del Quality Guard visibles en Stonks.
- Live continúa hard-locked (`LIVE_TRADING_ENABLED = False`).

## Valores conservadores por defecto

- calidad mínima: 55/100;
- cooldown por símbolo: 15 minutos;
- máximo 4 entradas por símbolo/día;
- Risk actual del usuario permanece sin cambios.

## Seguridad

Esta versión no garantiza rentabilidad. La finalidad es probar y aprender exclusivamente con Alpaca Paper, reduciendo sobreoperación y manteniendo el control Risk como autoridad final.

## Validación realizada en este entorno

- 63 tests deterministas Stonks PASS en módulos independientes de Flask.
- Python `compileall` PASS.
- 19 scripts JavaScript inline + JS estático: sintaxis PASS.
- Playwright no está instalado en este entorno, por lo que la batería visual completa no se repitió aquí.
