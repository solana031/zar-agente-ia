# ZAR v30.2.3 — Google live verification 500 fix

- Fixed a backend `NameError` in `/api/google/services/check`: the route uses `datetime`/`timezone` but they were not imported at module scope.
- This caused Railway to return an HTML 500 page, which the v30.2.2 frontend correctly surfaced as a server error.
- The endpoint now returns the intended JSON result so each Google service can be probed independently.
- No changes to Deep Research, Memory, Files, or Google backup behavior.
