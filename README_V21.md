# Zar V21 — Archivos inteligentes

V21 conserva la interfaz estable de V20.3 y añade análisis visual de archivos con Gemini/API.

- Los archivos se guardan en `/data/files` y no se vuelven a subir para analizarlos.
- `file_analyze` analiza facturas, recibos y documentos con Gemini y guarda una ficha estructurada.
- La ficha incluye tipo, categoría, resumen, proveedor, número de factura, fecha, vencimiento, total, moneda, impuestos, referencia y etiquetas cuando son legibles.
- El análisis visual no usa OpenRouter Free como fallback, para evitar consumir su cuota y para no convertir un límite 429 en un error de almacenamiento.
- Si OpenRouter está agotado, el archivo sigue guardado y puede analizarse con Gemini sin volver a adjuntarlo.


V21.2: Gemini permanece como proveedor principal. El fallback automático a OpenRouter está desactivado por defecto para evitar que el límite gratuito 429 de OpenRouter interrumpa el uso de Gemini. Para activarlo explícitamente, crea en Railway ZAR_ALLOW_OPENROUTER_FALLBACK=true.
