# ZAR v27.26 · Google Login + Service Status

- La raíz de Zar muestra una pantalla de inicio con estilo Zar cuando no existe una autorización Google persistente.
- La conexión OAuth usa el host exacto con el que el usuario abrió Zar y persiste el redirect URI junto a la transacción OAuth.
- El callback devuelve una pantalla Zar de conexión correcta con los servicios Google activos.
- Al volver a `/`, si existe refresh token válido, Zar entra directamente al escritorio sin pedir autorización de nuevo.
- El escritorio muestra el número de servicios Google activos.
- El OAuth de Google no depende de PUBLIC_BASE_URL para el redirect de la autorización, evitando conflictos entre alias de Railway.

Nota: el URI exacto usado por la autorización debe estar autorizado en el cliente OAuth de Google Cloud. Google exige coincidencia exacta del redirect URI.
