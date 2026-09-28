# ZAR v31.3.2 — Motor de señales en tiempo casi real

## Objetivo
Añade un motor de análisis de señales sobre datos de mercado de Alpaca, sin ejecutar órdenes.

## Incluido
- `GET /api/stonks/signals`
- Datos de Alpaca Market Data con feed `iex` por defecto.
- Marcos `1Min`, `5Min` y `15Min`.
- Máximo 8 símbolos por análisis.
- Solo utiliza barras cerradas; se excluye la vela del minuto en curso.
- ZAR Trend: cruce SMA 20/50.
- ZAR Mean Reversion: cruces RSI 14 de niveles 30/70.
- Estado de mercado mediante el reloj de Alpaca Paper.
- Registro de señales BUY/SELL nuevas en el panel Registro IA en vivo.
- Actualización automática cada 30 segundos mientras la ventana ZAR Stonks esté abierta.
- Hora española para los timestamps mostrados en la interfaz.
- La señal no crea, modifica ni cancela órdenes.

## Seguridad
Esta versión continúa siendo Paper-first y análisis-only para el motor de señales. No existe conexión Live ni ejecución automática de señales.

Las credenciales de Alpaca siguen siendo únicamente variables de servidor:
- `ALPACA_PAPER_API_KEY`
- `ALPACA_PAPER_API_SECRET`

## Prueba recomendada
1. Subir el ZIP a la raíz de `solana031/zar-agente-ia`.
2. Dejar actuar al workflow automático existente.
3. Esperar a Railway y hacer `Ctrl+F5`.
4. Abrir **ZAR Stonks → Estrategias IA**.
5. Mantener `AAPL`, `ZAR Trend · SMA 20/50` y `1 minuto`.
6. Pulsar **Analizar ahora**.
7. Comprobar la tabla de señales y el panel **Registro IA en vivo**.
8. Cambiar a `ZAR Mean Reversion · RSI 14` y repetir.
9. Probar varios símbolos separados por comas, por ejemplo `AAPL,MSFT`.

## Importante
El resultado `BUY`, `SELL` o `ESPERAR` es una señal técnica basada en las reglas implementadas; no es una predicción ni una orden de mercado.
