# ZAR v32.1.2 — Workspace Background Context Fix

- Corrige `Working outside of request context` en el chat asíncrono.
- Cada job reconstruye un request context Flask aislado y restaura la sesión necesaria.
- Conserva confirmaciones Workspace, identidad de usuario/browser y Google OAuth en ejecución diferida.
- No modifica Stonks, Risk, Paper, Shadow ni LIVE.
