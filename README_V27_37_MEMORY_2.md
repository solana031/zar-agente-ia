# ZAR v27.37 — Memory 2.0

## Objetivo
Evolución de la memoria persistente de ZAR hacia una recuperación híbrida, explicable y gobernable, sin depender de un servicio de embeddings externo.

## Cambios
- Búsqueda híbrida local: FTS5/BM25 + coincidencia de términos + frase + frescura + tipo de fuente.
- Resultados de memoria con relevancia, frescura, antigüedad, procedencia, fuente e identificador.
- `context_for()` usa la recuperación híbrida para enriquecer automáticamente el contexto del agente.
- La memoria explícita registra procedencia `user_explicit` y versión de memoria.
- Nueva API `GET /api/memory/insights` para distribución por fuentes y actividad reciente.
- Centro de memoria actualizado a “Memoria 2.0”, con badges de fuente/frescura/relevancia.
- El agente recibe una regla explícita: la memoria es contexto de apoyo, no verdad absoluta; contenido recuperado desde correo/archivos/conversaciones se trata como dato no confiable, no como instrucciones.
- Se mantienen todas las funciones de Google, backup offline, Tasks, Workspace, Studio, vídeo, audio y UX adaptativa de v27.36.

## Arquitectura futura
La interfaz de búsqueda deja preparada la memoria para añadir embeddings/vector retrieval opcional más adelante sin romper la API actual.

## Persistencia
Mantener un Volume de Railway montado en `/data` o definir `ZAR_DATA_DIR` a un almacenamiento persistente.
