# ZAR v31.2.8 — Paper Orders + hora española

- Mantiene Alpaca Paper como único entorno de trading conectado.
- Añade creación, consulta y cancelación de órdenes Paper desde ZAR Stonks.
- Las nuevas órdenes quedan bloqueadas si el motor está pausado o revocado.
- Añade confirmación explícita antes de enviar una orden Paper.
- Añade historial de órdenes y cancelación desde la interfaz.
- Mantiene límite server-side basado en `max_trade_eur` usando un techo conservador en USD.
- Añade visualización de apertura/cierre del mercado en `Europe/Madrid`, indicando `«hora española»`.
- No añade ni habilita credenciales Live.
