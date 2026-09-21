# ZAR v30.2.4 — OAuth service chips UI fix

Corrige la pantalla de conexión correcta de Google. El selector CSS `.ok` del indicador de éxito estaba afectando también a los servicios con clase `.svc.ok`, provocando que el estado `Activo` se superpusiera con el icono.

Cambios:
- El indicador de éxito usa ahora `.oauthOk`.
- Los servicios `.svc` tienen estructura vertical estable: icono → nombre → estado.
- `Activo`/`Pendiente` queda siempre debajo del nombre.
- Se conserva toda la funcionalidad de v30.2.3.
