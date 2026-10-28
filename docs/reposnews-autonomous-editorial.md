# Respaldo editorial de ReposNews

El titular puede activar o pausar la generación y publicación desde la mesa editorial de ReposNews. La autorización es persistente y está limitada a este horario y finalidad; no equivale a aprobar cualquier borrador ni cambia las decisiones individuales sobre Reels.

- De lunes a viernes a las 18:00, zona `Europe/Madrid`, incluidos los cambios de hora.
- La activación comienza en el próximo horario futuro. Si el servidor vuelve después de las 18:00, puede recuperar el trabajo del mismo día; no recupera días anteriores.
- Solo actúa cuando ningún Reel nuevo recibido ese día ha producido un artículo completo. Los backfills antiguos no desactivan el respaldo. Vuelve a comprobar la condición antes de cada publicación.
- Consulta GitHub Trending mensual y conserva origen, fecha, posición y estrellas ganadas ese mes. No calcula viralidad a partir de las estrellas acumuladas.
- Omite repositorios ya presentes, tanto públicos como privados. Investiga las fuentes oficiales y utiliza el generador y la revisión editorial bilingüe existentes. No inventa cifras ni comandos.
- Publica hasta cuatro guías con portada editorial propia. El objetivo es tres o cuatro; si no puede verificar suficientes proyectos, publica menos y muestra el resultado parcial.
- Conserva STOP GLOBAL, revisión legal, controles JEV, revisión del contenido y validación de portada. No modifica anuncios, fiscalidad, OAuth, vídeo ni permisos de otras plataformas.
- Los trabajos se guardan por día con exclusión entre procesos, arrendamiento recuperable y puntos de control. Máximo ocho candidatos y dos arranques por día, con espera de treinta minutos tras un fallo de la fuente.

El proceso se ejecuta en Railway dentro de ZAR. No necesita Codex, una pestaña abierta ni el ordenador del titular. Si ZAR está detenido todo el día, no puede ejecutar el horario de ese día.

Las pruebas automatizadas usan fuentes y servicios simulados. No generan ni publican contenido en cuentas reales. La activación en producción debe comprobarse por separado después del despliegue.
