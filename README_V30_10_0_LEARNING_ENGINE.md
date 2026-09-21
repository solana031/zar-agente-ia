# ZAR v30.10.0 — motor de aprendizaje y confirmaciones

- Las búsquedas de aprendizaje no pueden bloquear indefinidamente el worker: cada búsqueda tiene una ventana máxima y después usa el buscador público alternativo.
- Las consultas completadas se contabilizan aunque una fuente falle.
- El estado muestra tiempo, fuentes y consultas durante el proceso.
- Reanudar cambia inmediatamente la UI a estado de reanudación y elimina el botón «Reanudar» hasta que vuelva a estar pausado.
- Eliminación de aprendizajes y habilidades usa un diálogo de confirmación propio de ZAR con «No, conservar» y «Sí, eliminar definitivamente».
- Los datos persistentes siguen fuera del ZIP.
