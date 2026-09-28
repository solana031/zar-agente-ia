# ZAR v31.3.3 — Decision + Risk + Paper Execution

## Objetivo
Conectar el motor de señales de ZAR Stonks con una capa de decisión y Risk, con ejecución exclusivamente en Alpaca Paper.

## Nuevos endpoints
- `POST /api/stonks/decision`: recalcula la señal actual en servidor, comprueba estado, mercado y límites Risk y, si `execute=true`, puede crear una orden **solo Paper**.
- `GET /api/stonks/audit`: registro de auditoría por usuario.
- `POST /api/stonks/controls`: además de los límites, guarda `execution_mode` (`decision` o `paper_auto`).

## Modos
- **Evaluar señales · sin órdenes**: valor por defecto. Las señales pasan por Decision + Risk pero no crean órdenes.
- **Paper automático · con Risk**: requiere confirmación explícita en Configuración Risk. Cuando ZAR está reanudado y no revocado, una señal BUY/SELL que pase todos los controles puede generar una orden de mercado DAY en Alpaca Paper.

## Barreras
- Revocado o pausado => no se ejecuta.
- Modo distinto de Paper => no se ejecuta.
- Mercado cerrado => no se ejecuta.
- Pérdida diaria máxima => no se ejecuta.
- Máximo por operación => no se ejecuta.
- Máximo de posición => no se ejecuta.
- SELL requiere posición Paper existente y no permite vender más de la posición.
- Señal se recalcula en servidor y debe coincidir con la señal enviada.
- Dedupe por símbolo/estrategia/timeframe/barra/señal evita repetir la misma señal.
- Auditoría registra decisiones, cambios de Risk y órdenes Paper.
- Las credenciales permanecen en servidor.
- **No existe ruta Live en esta versión.**

## Validación
- `app/main.py` compila con `py_compile`.
- Los scripts inline de `index.html` pasan `node --check`.
