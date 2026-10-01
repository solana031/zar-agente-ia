# ZAR v31.3.48 — Stonks Market Stream Manager

## Objetivo
Mantener datos de mercado en tiempo real sin usar LLMs en el camino normal.

## Cambios
- Nuevo `Market Stream Manager` determinista y 0 tokens.
- WebSocket de acciones/ETF mediante feed Alpaca IEX por defecto.
- WebSocket de crypto mediante Alpaca Crypto por defecto.
- Soporte opcional de contratos de opciones mediante feed indicative/MsgPack cuando se configuren contratos explícitos.
- Caché en memoria de último trade, bid/ask y barra recibida.
- Suscripciones dinámicas según símbolos del motor y watchlists persistidas.
- Máximo por defecto de 30 acciones/ETF para respetar el límite típico del plan Basic; configurable por entorno.
- Estado y últimos precios visibles dentro de `ZERO-TOKEN DATA PLANE`.
- Nuevo subagente `Market Stream` visible en Stonks y Orquestación.
- `Self-Test` incluye el nuevo especialista en la arquitectura crítica.
- Corregida la versión visual antigua v31.3.45 en el panel Stonks.

## Seguridad y coste
- El stream no tiene autoridad de orden.
- 0 llamadas GPT/Gemini.
- 0 tokens de IA.
- La ruta de órdenes sigue separada y Paper-only.

## Dependencias
- websocket-client
- msgpack (solo necesario para stream de opciones)
