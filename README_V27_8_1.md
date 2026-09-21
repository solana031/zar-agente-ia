# Zar V27.8.1 — Healthcheck crash fix

## Qué se ha corregido
El deployment de V27.8 fallaba al arrancar con:
`AssertionError: View function mapping is overwriting an existing endpoint function: health`

La causa era una segunda definición de `@app.get("/health")` en `app/main.py`.
V27.8.1 elimina la definición duplicada y conserva el endpoint original.

## Instalación
Sustituye el contenido del repositorio de GitHub, haz Commit changes y deja que Railway despliegue.
No cambies variables ni el volumen.
