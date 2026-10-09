# ZAR 33.3.17 · verificación real

Fecha: 2026-10-09. Producción Railway comprobada con `/health` (`ok: true`, versión `33.3.17`) y despliegue SUCCESS del commit `a232b770a74ffc25bf0e49e326ac33f7d30e905b`.

## Orquestación y Workspace

- Producción real: 390×844, 393×852 y 412×915. Altura útil del mapa: 430,5 / 435,2 / 471,7 px; filtros cerrados debajo; ancho de documento coincidente con viewport.
- Menú móvil: las 17 entradas inspeccionadas tienen alto mínimo de 60 px y no desbordan horizontalmente.
- Workspace carga cinco documentos existentes de la sesión verificada. Perfil editable vacío; no se han inventado datos de empresa ni modificado documentos. Las anotaciones, clasificación, historial y reconstrucción se validan con almacenamiento aislado y APIs simuladas.

## Único smoke real de DramaClaw

- Historia: «Una semilla brota al amanecer.»
- Objetivo: 5 segundos, 9:16, máximo 1 escena. No se publica en redes.
- Trabajo ZAR: `72b5ce5a77834a46`.
- Proyecto DramaClaw: `01M4GWNASXFTXGP2MMB5245CDC`, nombre `ZAR_bebb7f12d7d54505bd91`.
- Proyecto, configuración, subida, ingestión y episodio creados. El editor confirma 35 caracteres importados y 29 facturables.
- La tarea Build characters terminó; Asset Library confirma **0 personajes**. La planificación `identities` fue rechazada por un prerrequisito del proveedor. ZAR conserva la intención y los IDs, muestra `submission_unknown / prerequisite`, y no repite automáticamente la operación.
- **No se obtuvo MP4.** No se alcanzaron render, exportación ni preview real. El fallo observado es anterior a media storage y al player; no se atribuye a Cloudinary.
- No se hicieron nuevos proyectos ni reintentos de pago. El adaptador no devuelve coste monetario verificable; no se presenta una estimación como coste real.
- Pendiente: revisar la extracción/personajes del proyecto en DramaClaw y resolver el prerrequisito antes de reanudar los mismos IDs. Una historia de paisaje no produjo un reparto válido para este pipeline.

## Pruebas focalizadas

- Python: 38 pruebas y 6 subpruebas correctas (Workspace, Media y cliente DramaClaw); sintaxis de módulos modificados correcta.
- Mapa/menú, subapps y Workspace: cinco viewports con APIs simuladas.
- Stonks: siete viewports; comprobaciones existentes de renderizado, chat y Position Management conservadas. No se enviaron órdenes.
- Pulido visual: seis viewports. Player Clipper: links MP4 autenticados, error de carga y ausencia de publicación automática comprobados con mocks; esto no demuestra un MP4 real.
- YouTube figura conectado; Instagram/TikTok requieren configuración. No se verificó publicación real ni se enviaron correos.
- No se hizo una auditoría exhaustiva de cada pantalla, prueba en dispositivo físico ni OCR de PDF escaneados.
