# ZAR v30.10.27 — Voz sin duplicados + chat móvil desplazable

- El área de conversación móvil es ahora el único contenedor de scroll: el logo/home se desplaza hacia arriba y deja el espacio al historial.
- Se puede deslizar libremente para volver a mensajes anteriores y llegar de nuevo al mensaje actual.
- Los controles de scroll usan el mismo contenedor en móvil y escritorio.
- El reconocimiento legacy ya no concatena resultados intermedios repetidos: separa finales/intermedios y usa resultIndex.
- La transcripción PRO y Live aplican una limpieza conservadora de bloques repetidos para eliminar duplicaciones causadas por el motor/transmisión sin borrar repeticiones cortas intencionadas.
- Se mantienen las rutas API, la lógica del agente y las integraciones existentes.
