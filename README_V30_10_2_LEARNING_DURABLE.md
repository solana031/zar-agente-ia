# ZAR v30.10.2 — Aprendizaje persistente por pasos

Esta versión corrige el aprendizaje que podía quedarse en 5% cuando el hilo en segundo plano del servidor web dejaba de avanzar.

## Cambio principal
- El aprendizaje ya no depende de un hilo daemon de Flask/Gunicorn.
- Cada consulta de investigación se procesa como un paso persistido en `learning.json`.
- El endpoint de estado puede avanzar exactamente un paso y guardar el resultado.
- Si Railway reinicia el proceso, el trabajo puede continuar desde `query_index`.
- Se guarda la consulta actual, consultas completadas, fuentes y resultados intermedios.
- Las búsquedas tienen un presupuesto de tiempo para evitar bloqueos indefinidos.
- Se mantiene el borrado, reanudación y progreso de la UI.

## Resultado esperado
El aprendizaje debe pasar de 5% a porcentajes superiores y mostrar `1/7`, `2/7`, etc., además de aumentar las fuentes cuando las consultas producen resultados.
