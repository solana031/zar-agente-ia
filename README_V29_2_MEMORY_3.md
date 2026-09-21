# ZAR v29.2 — Memory 3.0

## Objetivo
Evolucionar la memoria de ZAR sin romper Memory 2.0 ni las integraciones existentes.

## Incluye
- Memoria semántica con Gemini Embedding 2 (`gemini-embedding-2`) a 768 dimensiones.
- Búsqueda híbrida: semántica + coincidencia textual + importancia + frescura.
- Clasificación automática de recuerdos: permanente/preferencia, temporal o hecho.
- Importancia estimada y categoría (`project`, `preference`, `work`, `location`, `planning`, `general`).
- Caducidad para recuerdos temporales.
- Índice separado `memory3` dentro de la base SQLite por usuario.
- Migración no destructiva de recuerdos explícitos existentes de Memory 2.0.
- Panel de Memoria 3.0 con estadísticas, búsqueda semántica, recuerdos recientes y reindexado.
- Fallback local: si Gemini Embedding 2 no está disponible, la memoria sigue funcionando con recuperación léxica.
- Las credenciales permanecen en servidor; nunca se envían al navegador.

## Compatibilidad
Memory 2.0, conversaciones, archivos, Google, Studio, voz, Live, TTS y el resto de ZAR se mantienen.
