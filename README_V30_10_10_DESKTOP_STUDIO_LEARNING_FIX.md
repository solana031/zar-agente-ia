# ZAR v30.10.10 — Desktop workspace, Studio reliability and durable learning

- El compositor y los botones rápidos ocupan el espacio real entre panel izquierdo y derecho.
- Panel derecho con contraer/abrir y Ctrl+B; el centro se reajusta.
- Habilidades activas y estado de aprendizaje más legibles.
- Corregido `editorTarget is not defined`, que impedía abrir el editor de vídeo.
- Pulidas las superficies de vídeo, imagen y audio de ZAR Studio.
- Aprendizaje convertido a avance durable por polling: se persiste cada paso y no depende de workers daemon locales.
- Se mantiene el límite de 60 minutos y no se genera progreso falso ante errores.
