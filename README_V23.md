# Zar V23 — Google Maps, Places y Routes

Añade herramientas para buscar lugares, abrir búsquedas universales de Google Maps y calcular rutas mediante Google Routes API cuando exista `ZAR_MAPS_API_KEY`.

## Nuevas herramientas
- `maps_search`: búsqueda de lugares con Places API (New).
- `maps_open_search`: abre Google Maps mediante Maps URL; no necesita API key.
- `maps_directions`: abre indicaciones y, con API key, devuelve distancia y duración mediante Routes API.
- `maps_status`: comprueba configuración.

## Variable de Railway
`ZAR_MAPS_API_KEY` — API key específica de Google Maps Platform.

Se recomienda restringir esta clave a las APIs realmente usadas: Maps JavaScript API, Places API (New) y Routes API.

No se modifican los permisos OAuth de Gmail, Calendar o Google Workspace.
