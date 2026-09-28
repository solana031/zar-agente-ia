# ZAR v31.3.7 — Risk Engine Hardening

Base: v31.3.6

## Objetivo

Endurecer la cadena de decisión de ZAR Stonks antes de la primera orden Paper controlada.

## Cambios

- Corrige la lectura del precio en el endpoint de última operación de Alpaca para soportar la respuesta de símbolo único (`symbol` + `trade`) y, como respaldo, la respuesta plural (`trades`).
- La comprobación de precio válido ya no puede marcar como ausente un precio que sí fue recibido.
- La evaluación Risk devuelve `checks` individuales y `primary_reason`.
- La auditoría guarda los controles y el motivo principal de la decisión.
- Para SELL se comprueba que exista una posición Paper y no se aplica artificialmente un suelo de 1 USD al valor de cierre de una posición existente.
- Para BUY se mantiene el suelo operativo de 1 USD y el límite configurado por operación.
- La cantidad se conserva con hasta 9 decimales para soportar fracciones.
- La interfaz muestra el motivo principal en los eventos de auditoría y en los bloqueos Risk.
- Versión visual actualizada a v31.3.7.

## Seguridad

- Solo Alpaca Paper.
- Live no está conectado.
- Pausa y revocación siguen teniendo prioridad.
- El modo por defecto continúa siendo `Evaluar señales · sin órdenes`.
- `Paper automático` requiere activación explícita y `Stonks` reanudado.
- La ejecución manual continúa requiriendo confirmación explícita.

## Prueba prevista

1. Mantener `Evaluar señales · sin órdenes`.
2. Generar una señal BUY/SELL.
3. Comprobar `DECISIÓN` en auditoría con `primary_reason` y `checks`.
4. Confirmar que no se crea ninguna orden.
5. Solo después realizar una única orden Paper controlada desde `Evaluar / Paper`.
