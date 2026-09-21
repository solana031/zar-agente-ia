# ZAR v27.28 — OAuth redirect_uri mismatch fix

- Google reported `Error 400: redirect_uri_mismatch` after account selection.
- Railway reverse-proxy headers are now respected when constructing the public OAuth callback.
- `GOOGLE_REDIRECT_URI` takes priority; otherwise `PUBLIC_BASE_URL`; otherwise X-Forwarded-Proto/Host are used.
- Google OAuth request includes `include_granted_scopes=true`.
- The same exact redirect URI is persisted and reused during token exchange.
- Intended production callback: `https://web-production-273da.up.railway.app/oauth2callback`.
