# ZAR v31.3.16 — Supervisión y reconciliación del ciclo Paper

## Objetivo
Convertir el motor autónomo continuo en un proceso que no solo evalúa señales, sino que también reconcilia de forma persistente el estado real de la cuenta Paper antes y después de cada ciclo.

## Cambios
- Reconciliación servidor de posiciones y órdenes Paper abiertas.
- La reconciliación no crea ni cancela órdenes.
- Si existe una orden abierta para un símbolo, el motor no intenta enviar otra orden para ese símbolo hasta que Alpaca confirme/cierre la existente.
- Decision + Risk incorpora un control `OPEN_ORDER` para evitar órdenes superpuestas incluso fuera del ciclo autónomo.
- El estado persistido muestra última reconciliación, posiciones conocidas y órdenes abiertas conocidas.
- La interfaz muestra el contador de posiciones/órdenes abiertas y la hora de la última reconciliación.
- El motor sigue siendo continuo (~5 s), Paper-only, con PAUSA/REVOCAR por encima de la ejecución.

## Ciclo
Mercado → reconciliación → señal → Decision + Risk → orden Paper (si procede) → reconciliación posterior → auditoría.

## Seguridad
No se conecta Live, no se añaden permisos de retirada y la reconciliación es solo observacional.
