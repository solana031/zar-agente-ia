# ZAR v30.10.3 — aprendizaje con búsqueda en cascada

Esta versión mantiene la arquitectura de aprendizaje persistente de v30.10.2 y corrige el caso en que una consulta de investigación devuelve cero fuentes o un proveedor deja de responder.

## Cambios
- Cada consulta usa una cascada de búsqueda:
  1. consulta original mediante Google Search grounding;
  2. variante con guía/manual/tutorial profesional;
  3. variante `filetype:pdf` para manuales, cursos y material PDF accesible legalmente;
  4. variante centrada en documentación oficial y recursos educativos;
  5. variante de ebook/acceso abierto;
  6. búsqueda pública alternativa sin clave cuando las vías anteriores no funcionan.
- Si una vía falla, ZAR no detiene el aprendizaje: registra el intento y continúa.
- Las fuentes se deduplican y se conservan en el aprendizaje.
- Se priorizan fuentes oficiales, educativas, universidades, editoriales, organizaciones profesionales y material de acceso legítimo; no se busca deliberadamente material pirateado.
- El estado informa cuántas vías se han probado cuando ha sido necesario usar fallback.
- La estimación de tiempo se recalcula a partir del tiempo real de las consultas, en lugar de quedarse con una estimación fija.
- El progreso sigue siendo durable: cada consulta terminada queda guardada antes de pasar a la siguiente.
- Se mantienen la reanudación, eliminación y actualización inmediata de la interfaz introducidas en v30.10.x.

## Ejemplo
Para fotografía, ZAR puede buscar no solo páginas generales, sino también:
- técnicas profesionales de composición, exposición e iluminación;
- manuales y documentación de edición;
- cursos y guías prácticas;
- PDFs de acceso legítimo;
- documentación de herramientas de edición cuando aparezcan en los resultados;
- recursos profesionales y educativos.

El aprendizaje inicial no equivale a dominio absoluto: ZAR guarda el conocimiento, fuentes y comprobaciones para poder seguir ampliándolo.
