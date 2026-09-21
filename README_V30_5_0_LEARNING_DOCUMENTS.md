# ZAR v30.6.0 — Aprendizaje persistente + comprensión documental

## Aprendizaje
- Comando natural: «quiero que aprendas…», «aprende a…», «estudia…», «domina…».
- Investigación web en segundo plano con varias consultas y fuentes.
- Plan de estudio persistente, comprobaciones de dominio y referencias.
- Creación de una habilidad reutilizable a partir del aprendizaje.
- Las habilidades aprendidas aparecen junto a las habilidades del usuario.
- No modifica automáticamente el código, permisos ni credenciales de ZAR.

## Documentos
- La ficha documental admite facturas, nóminas, contratos, recibos, PDFs, imágenes y documentos generales.
- Extrae texto legible, fechas, importes, divisas, impuestos, líneas, entidades, personas, identificadores, tablas y observaciones visuales cuando sean legibles.
- «Aprende de este documento» usa el último archivo adjunto y conserva el aprendizaje en el almacenamiento persistente.

## Persistencia
Todo el estado de aprendizaje vive en `ZAR_DATA_DIR/users/<usuario>/learning/` y no se incluye en el ZIP de release.
