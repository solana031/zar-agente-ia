# ZAR v31.3.25 — Efficient Agents Foundation

Esta versión parte de v31.3.24 y añade una primera fase compatible de la arquitectura propuesta por ZAR, sin sustituir los flujos existentes.

## 1. Home UI
- Restaura únicamente la colocación anterior de icono, nombre y descripción en las tarjetas de escritorio.
- Conserva el resto del UI polish de v31.3.23/v31.3.24.

## 2. Safe Execution Gateway + Bus
- Todas las herramientas ejecutadas por el agente pasan por una capa única de política y auditoría.
- Las consultas de solo lectura pueden reintentarse una vez ante un fallo transitorio.
- Las acciones sensibles quedan etiquetadas separadamente y siguen usando las confirmaciones existentes de ZAR.
- Se crea una cola durable para futuros trabajos autónomos/subagentes sin acoplarla todavía a acciones críticas.

## 3. Memoria híbrida + grafo de contexto
- Se conserva Memory 3.0 (vectorial + lexical).
- Se añade un grafo SQLite por usuario para relacionar correo activo, borrador, contacto, tarea, archivo, proyecto y memorias relevantes.
- El prompt recibe un subgrafo pequeño en vez de depender de más historial bruto.
- Se reduce el fallback de recuerdos recientes para ahorrar contexto/tokens.

## 4. Router de subagentes sin tokens
- Clasificador determinista local: Gmail, Calendar, Contacts, Workspace, Files, Research, Maps, Studio y Media.
- Una petición clara recibe solo las herramientas de su dominio + herramientas núcleo.
- Peticiones desconocidas o demasiado multidominio conservan el catálogo completo como fallback de seguridad.
- Esta base está preparada para los subagentes específicos de ZAR Stonks en la siguiente iteración.

## Compatibilidad
- No cambia las rutas de confirmación existentes.
- No habilita trading real.
- No modifica el comportamiento operativo del motor Stonks salvo el texto de versión mostrado.
