# ZAR v30.1.0 — Deep Research 2.0 + Memoria y Archivos 2.0

## Bloques incorporados

### Bloque 1 — Deep Research 2.0
- Las imágenes públicas ya no se concentran únicamente en la portada.
- ZAR utiliza una portada visual más contenida y distribuye el resto de imágenes a lo largo del análisis.
- Las imágenes intercaladas se adaptan automáticamente: laterales, derecha/izquierda o ancho completo según su posición.
- En móvil pasan a ancho completo para evitar columnas estrechas.
- Las tablas Markdown siguen renderizándose como tablas y pueden generar comparativas visuales únicamente con datos presentes en ellas.
- Las citas y fuentes siguen siendo clicables.

### Bloque 2 — Memoria + Archivos 2.0
- Conversaciones, memoria, archivos e investigaciones permanecen fuera del código de la versión.
- La biblioteca de archivos se indexa automáticamente al subir documentos compatibles.
- ZAR puede recuperar fragmentos relevantes de archivos y documentos como contexto real para responder al usuario.
- Se añade `/api/files/context` para recuperar contexto documental.
- Se añade `/api/persistence/status` para comprobar cuántas conversaciones, recuerdos, archivos e investigaciones conserva ZAR y cuántos fragmentos están indexados.
- El panel Memoria muestra el estado de persistencia.
- El Explorador de archivos muestra el estado de almacenamiento e indexación.
- La separación por usuario/cuenta se mantiene mediante el ámbito de ZAR.
- No se incluye `data/` dentro del ZIP de release, para evitar sobrescribir los datos existentes al actualizar.

## Persistencia Railway
Railway necesita un Volume montado en `/data` para que los datos sobrevivan a reinicios/redeploys. El endpoint de persistencia lo deja visible en la interfaz.

## Versión
`30.1.0`
