# ZAR v27.25 — OAuth host fix

- Forces Google/YouTube OAuth initiation onto PUBLIC_BASE_URL when an alternate Railway alias is used.
- Keeps Flask session cookies secure and SameSite=Lax.
- Clears stale OAuth session keys before starting a new flow.
- Fixes the frontend `async async function showMemory()` syntax error.
- Google status pill now explicitly shows connected/re-authorize/not connected.
