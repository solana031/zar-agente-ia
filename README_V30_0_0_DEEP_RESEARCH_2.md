# ZAR v30.0.0 — Deep Research 2.0

## Bloque 1 de ZAR v30

Esta versión mantiene el motor Deep Research que ya estaba funcionando y mejora la capa de presentación del informe.

### Incluido
- Portada editorial para cada investigación.
- Búsqueda visual con varias consultas derivadas del tema, en lugar de usar la petición completa como una sola consulta de imágenes.
- Fallback visual elegante cuando no existen imágenes públicas suficientemente relevantes.
- Tablas Markdown convertidas a tablas HTML profesionales.
- Comparativas visuales mediante barras cuando una tabla contiene datos numéricos comparables.
- Citas numeradas convertidas en enlaces visuales dentro del informe cuando Deep Research las devuelve como Markdown.
- Fuentes presentadas como tarjetas navegables.
- Diseño responsive y preparación para impresión.
- No se generan cifras nuevas para los gráficos: las comparativas visuales usan exclusivamente datos presentes en las tablas del informe.

## Persistencia v30

Las actualizaciones de código no deben borrar conversaciones, memoria, archivos, investigaciones ni estado de Google.

- Railway sigue utilizando `ZAR_DATA_DIR=/data` cuando está configurado.
- En instalaciones locales de Windows, ZAR v30 utiliza un directorio estable del usuario (`%LOCALAPPDATA%\\ZAR\\data`) independiente de la carpeta del código.
- Si existe el antiguo `data/` dentro del proyecto y todavía no existe el directorio estable, v30 realiza una migración inicial.
- Las conversaciones archivadas ya no tienen el límite histórico de 200 hilos; la interfaz puede paginar lo que muestra, pero el almacenamiento no descarta hilos por antigüedad.
- Los ZIP de release excluyen `data/` para que los datos no se empaqueten ni sobrescriban al actualizar.

### Importante para Railway
La persistencia de `/data` depende de que el servicio Railway tenga un Volume montado en `/data`. La aplicación ya informa de este requisito en su Centro de control.
