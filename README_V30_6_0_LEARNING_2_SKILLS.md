# ZAR v30.6.0 — Learning 2.0 + Skills reales

## Aprendizaje observable
- Progreso por fases: preparación, investigación, síntesis y creación de capacidad.
- Métricas persistentes: consultas completadas, fuentes encontradas, tiempo transcurrido y estimación restante.
- Hasta siete consultas iniciales, con hasta tres búsquedas simultáneas para reducir la latencia sin lanzar una avalancha de peticiones.
- Fuentes deduplicadas y currículo con comprobaciones de dominio.
- Los trabajos se conservan en `/data` y pueden reanudarse si una instancia de Railway reinicia el proceso.

## Conocimiento reutilizable
El aprendizaje inicial guarda un resumen, currículo, comprobaciones, fuentes y un digest de investigación. El agente recupera conocimiento aprendido relevante para la petición actual y las habilidades aprendidas lo incorporan durante su ejecución.

## Habilidades 2.0
Las habilidades conservan pasos, herramientas, activadores, categoría y referencia al aprendizaje que las originó. La ejecución instruye al agente a utilizar herramientas reales, verificar resultados y respetar confirmaciones de seguridad.

## Documentos
El análisis documental existente conserva extracción estructurada de texto, idioma, tipo de documento, personas, entidades, fechas, identificadores, divisa, importes, impuestos, descuentos, líneas y observaciones visuales cuando el archivo es legible para el modelo.

## Limitación importante
Aprender un dominio no implica dominio absoluto. Para idiomas, programación, fotografía u otras disciplinas, ZAR construye un currículo y pruebas de dominio; puede seguir practicando, actualizar fuentes y ampliar la capacidad bajo petición.
