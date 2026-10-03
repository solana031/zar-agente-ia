# ZAR 32.1.16 — Automaton Mode en Stonks

- Nuevo **Automaton Mode** dentro de ZAR Stonks, inspirado en el patrón continuo `Think → Act → Observe → Repeat` del proyecto Conway Automaton.
- Integración nativa en Python: no añade Node/TypeScript ni crea un segundo motor de órdenes.
- Estados persistentes: `OFF`, `RUNNING`, `PAUSED`.
- Controles UI: **Encender / Pausar / Apagar**.
- Encender activa el motor autónomo existente en `paper_auto` y reutiliza la ruta endurecida Quality → Decision → Risk → Alpaca Paper.
- Pausar conserva reconciliación, learning y gestión de seguridad, pero bloquea nuevas entradas de Automaton.
- Apagar desactiva nuevas acciones autónomas y conserva estado/journal.
- Métricas visibles: ciclos, heartbeat, fase, activo, decisión, P/L, trades, win rate y aprendizaje.
- Journal persistente de Automaton.
- Métricas de P/L/trades calculadas desde el arranque de la sesión Automaton, no desde todo el histórico de ZAR.
- LIVE continúa hard-blocked; Automaton no tiene wallet, shell, self-replication ni auto-modificación libre.
- Stonks mantiene Risk, Quality Guard, cooldowns, ledger, reconciliación, client_order_id y kill switches existentes.

Base: 32.1.15.
