# ZAR v30.2.2 — Google live verification fix

- Hardened `/api/google/services/check` so Google session/credential failures return JSON instead of an HTML error page.
- Hardened the control-center frontend to validate the response content type before parsing JSON.
- Shows a precise message when an old deployment does not expose the live verification endpoint instead of `Unexpected token '<'`.
- Preserves Google 2.0, Memory + Files 2.0 and Deep Research 2.0.
