# ZAR v32.1.14 — Confirmation payload fix

- Workspace confirmations no longer depend on finding the target Google Sheet before rendering Confirmar/Cancelar.
- Analyze-first business/closure flows persist a deferred structured action immediately, so the buttons can render in the same assistant response.
- The exact Room108 spreadsheet is resolved only after Confirmar; Cancelar performs no Google mutation.
- Keeps the idempotent Google Sheets banding fix from v32.1.13.
- No Stonks logic changed.
