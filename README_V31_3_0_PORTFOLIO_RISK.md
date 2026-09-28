# ZAR v31.3.0 — Portfolio Paper + Risk Guard

## Objetivo
Siguiente bloque operativo de ZAR Stonks después de validar el circuito de órdenes/cancelaciones Paper.

## Añadido
- `GET /api/stonks/alpaca/portfolio`
  - Cuenta Paper actual.
  - Equity, cash, buying power, last equity.
  - P/L del día calculado contra `last_equity`.
  - Posiciones abiertas.
  - Estado del mercado y próxima apertura/cierre.
- `GET /api/stonks/alpaca/positions`
- `GET /api/stonks/alpaca/position/<symbol>`
- Dashboard con cartera Paper en tiempo real.
- Resumen de equity, P/L del día, número de posiciones y estado de riesgo.
- Tabla de posiciones con cantidad, precio medio, último precio, valor de mercado y P/L no realizado.
- Carteras & API incorpora la tabla de posiciones Paper.
- Configuración Risk muestra el estado del límite de pérdida diaria.

## Barreras de servidor para órdenes Paper
Antes de enviar una orden, el backend comprueba:
- control `paused/revoked/mode`.
- máximo por operación existente.
- mínimo de orden de Alpaca Paper.
- límite de pérdida diaria configurado.
- ventas solo contra posiciones Paper existentes y cantidad disponible.
- máximo de exposición por posición configurado.

Los límites se aplican en servidor; no dependen de que el navegador respete la interfaz.

## Seguridad / alcance
- Sigue siendo exclusivamente **Alpaca Paper**.
- No hay endpoint de trading Live.
- Las credenciales permanecen en Railway.
- No se ha implementado un motor autónomo que decida o ejecute operaciones por su cuenta.
- Las estrategias IA siguen siendo catálogo/laboratorio hasta que se construya un sistema de señales, backtesting reproducible y aprobación explícita.

## Verificación
- `app/main.py` compila con `py_compile`.
- JavaScript extraído de `index.html` pasa `node --check`.
