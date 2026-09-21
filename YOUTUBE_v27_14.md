# ZAR v27.14 — YouTube

Añade integración de YouTube sin modificar el OAuth general de Google.

## Railway variables

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI` (recomendado): `https://TU-DOMINIO/youtube/callback`

## Flujo

1. `/youtube/connect` autoriza YouTube.
2. `/youtube/status` comprueba canal.
3. `/youtube/upload` permite subir vídeo y, opcionalmente, programarlo.
4. ZAR debe pedir confirmación al usuario antes de llamar al endpoint de subida/programación.

## Nota

El cliente OAuth de Google Cloud debe tener autorizado el callback exacto usado por Railway.
