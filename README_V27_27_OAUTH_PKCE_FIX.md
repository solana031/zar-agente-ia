# ZAR v27.27 — OAuth PKCE explícito

Esta versión sustituye la construcción del authorization request de Google por una implementación explícita y controlada en `app/cloud_auth.py`.

- Construye manualmente `response_type=code`.
- Usa `code_challenge_method=S256` y PKCE RFC 7636.
- Mantiene exactamente el mismo `redirect_uri` entre autorización e intercambio del código.
- Intercambia el código directamente contra `https://oauth2.googleapis.com/token`.
- Conserva `access_type=offline` para obtener/usar refresh token.
- Mantiene el almacenamiento persistente del token y la UX de login/servicios de v27.26.

## Configuración Railway

Usa como dominio único:

`https://web-production-273da.up.railway.app`

Y en Google Cloud debe existir exactamente:

`https://web-production-273da.up.railway.app/oauth2callback`

No hace falta crear un cliente OAuth nuevo.
