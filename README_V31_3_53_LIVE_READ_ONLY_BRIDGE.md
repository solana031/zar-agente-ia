# ZAR 31.3.53 — Live Read-Only Bridge

Base canónica: ZAR 31.3.52.

## Alcance

Esta release añade preparación para una futura cuenta real sin habilitar trading Live ni modificar la interfaz existente.

### Nuevo bridge Live read-only
- `LiveReadOnlyAdapter` usa exclusivamente HTTP GET.
- Credenciales separadas: `ALPACA_LIVE_READONLY_KEY` y `ALPACA_LIVE_READONLY_SECRET`.
- Puede leer cuenta, posiciones, órdenes abiertas y reloj del broker.
- No contiene métodos de compra, venta, cancelación, reemplazo o modificación.
- La telemetría se cachea durante 30 s para no consultar Alpaca cada ciclo de 5 s.
- Nunca usa GPT/Gemini: 0 tokens.

### Bloqueo Live
- `LIVE_TRADING_ENABLED = False` permanece fijo en código.
- `LiveExecutionAdapter` sigue sin poder construirse.
- `LiveSafetyGate` deniega toda escritura Live en servidor.

### Readiness
- `REAL MONEY READINESS` recibe un check adicional `Cuenta real read-only`.
- Si faltan credenciales, queda en pendiente.
- Si la conexión read-only funciona, muestra equity, cash y número de posiciones.
- El estado global sigue siendo `LIVE BLOQUEADO`.
- Readiness conserva 0 órdenes y 0 tokens.

### Self-Test
Añade invariantes para:
- LiveSafetyGate bloqueado.
- Adapter Live estrictamente read-only.
- Credenciales Live/Paper separadas.
- Ninguna autoridad Live para Learning/Readiness.

## Interfaz

No se ha modificado:
- `app/templates/index.html`
- CSS
- JavaScript de interfaz
- responsive
- Orquestación
- navegación
- PWA/WebView

La información adicional se integra a través del checklist dinámico de Readiness existente.

## Variables futuras

No se incluyen secretos en Git. Cuando se quiera probar la conexión real solo lectura, configurar manualmente en Railway:

- `ALPACA_LIVE_READONLY_KEY`
- `ALPACA_LIVE_READONLY_SECRET`

No configurar ninguna variable que habilite trading Live: no existe soporte de ejecución Live en esta release.

## Validación

- Bridge Live read-only: 10/10 tests aislados PASS.
- Self-Test: 19/19 invariantes PASS en fixture determinista.
- Paper transport regression: PASS.
- Python compileall: PASS.
- Cero órdenes reales y cero llamadas a broker real durante tests.
