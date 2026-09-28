# ZAR v31.3.13 — Motor autónomo Paper

## Objetivo
ZAR Stonks incorpora un motor servidor que puede continuar evaluando señales y ejecutando únicamente en Alpaca Paper aunque la ventana de Stonks esté cerrada.

## Seguridad
- El motor viene **desactivado por defecto**.
- Para activarlo se necesita una acción explícita desde Configuración Risk.
- Solo funciona con `mode=paper` y `execution_mode=paper_auto`.
- `PAUSA` bloquea nuevas ejecuciones.
- `REVOCAR` bloquea y además desactiva el motor autónomo.
- Cada ejecución reutiliza la ruta endurecida de `Decision + Risk`, incluida la comprobación de señal vigente, precio, posición, tamaño, pérdida diaria, máximo de operación, máximo de posición y duplicados.
- Live continúa desconectado.
- El motor usa las credenciales Alpaca exclusivamente en servidor.
- Como las credenciales Alpaca configuradas en esta arquitectura son globales, el motor autónomo se vincula a un único espacio de usuario de ZAR para evitar que dos espacios ejecuten sobre la misma cuenta Paper.

## Funcionamiento
- Ciclo servidor: cada 30 segundos.
- Símbolos, estrategia y timeframe se toman de la configuración del motor.
- Por defecto: `AAPL`, `trend`, `1Min`.
- Si el mercado está cerrado, el ciclo no envía órdenes.
- Si no hay BUY/SELL confirmado en una barra cerrada, no envía órdenes.
- El resultado y el último ciclo quedan persistidos en el estado de Stonks y aparecen en la interfaz mediante la sincronización automática de 5 segundos.

## Concurrencia
Railway/Gunicorn puede arrancar varios procesos. El motor utiliza un `flock` sobre `/data/stonks/engine.lock` para que solo un proceso ejecute los ciclos autónomos.

## Interfaz
- Nuevo bloque `MOTOR AUTÓNOMO PAPER` en Configuración Risk.
- Botón explícito para activar/desactivar.
- Estado del motor y último ciclo visibles.
- La ejecución automática del navegador no compite con el motor servidor cuando este está activo.

## Verificación local estática
- `python -m py_compile app/main.py` → correcto.
- JavaScript extraído de todos los `<script>` y comprobado con `node --check` → correcto.
- La prueba funcional contra Alpaca/Railway requiere ejecutar el ZIP desplegado con las dependencias y credenciales del entorno real Paper.
