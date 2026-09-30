# ZAR v31.3.4 — Audit + Paper Execution Hardening

Base: v31.3.3 Decision + Risk + Paper.

## Changes
- Corrected visible version label to v31.3.4.
- Risk tab now loads the audit trail when opened.
- Added emergency `DELETE /api/stonks/alpaca/orders` to cancel all open Alpaca Paper orders.
- Added UI action **Cancelar todas las órdenes Paper** with explicit confirmation.
- Global cancellation is audited and does not liquidate positions.
- Paper automatic mode now executes qualifying server-approved Paper signals without an extra browser confirmation dialog; server-side Risk, paused/revoked state, market-open check, signal revalidation and deduplication remain authoritative.
- Live execution remains impossible in this endpoint.

## Safety
- Default execution mode remains `decision` / no orders.
- Pause and revoke remain hard blockers.
- Credentials stay server-side.
- Global cancel only targets open orders in Alpaca Paper.
