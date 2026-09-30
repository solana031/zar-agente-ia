# ZAR v31 — ZAR Stonks Dashboard

- Nueva interfaz ZAR Stonks basada en el HTML de referencia aportado por el usuario.
- Dashboard, Estrategias IA, Órdenes, Carteras & API, Backtesting y Configuración Risk.
- Control operativo con Pausar/Reanudar y Revocar.
- Paper-first: v31 NO ejecuta órdenes reales.
- Estado persistente en `/data/stonks/<user>.json`.
- Alpaca/Kraken se muestran como conectores de servidor; las credenciales no se exponen al navegador.
- Próximo paso: implementar conectores, datos de mercado, backtesting real y motor de ejecución con kill switch.
