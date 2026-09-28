# Reglas de desarrollo de ZAR para Codex

Estas reglas se aplican a todo el repositorio. Las instrucciones explícitas de la tarea determinan su alcance; no introducir funcionalidades, publicaciones ni cambios de infraestructura no solicitados.

## 1. Fuente canónica y preparación

- La base canónica es `main` sincronizada con `origin/main`.
- Antes de modificar archivos, ejecutar en este orden: `git status`, `git branch --show-current`, `git fetch origin`.
- Si el árbol está limpio, cambiar a `main` y ejecutar `git pull --ff-only origin main`. Verificar que `HEAD` coincide con `origin/main` y leer los tres archivos VERSION.
- Si hay cambios locales, estudiarlos antes de continuar y preservarlos. No descartarlos, mezclarlos ni restaurar stashes automáticamente. Si las ramas divergen o no se puede actualizar con fast-forward, explicar el bloqueo sin sobrescribir trabajo.
- Nunca partir de un ZIP antiguo ni sustituir código nuevo por versiones anteriores. El historial y los ZIP sirven únicamente como referencias para comparar.

## 2. Estructura real del proyecto

- `app/main.py`: aplicación Flask, rutas API y lógica de servidor de Stonks, incluidos controles y motor Paper.
- `app/templates/index.html`: interfaz principal, HTML generado de Stonks, CSS y JavaScript inline. Revisar también el DOM generado, no solo el texto de la plantilla.
- `app/static/`: recursos y JavaScript/CSS externos, incluidos `skills.js` y `skills.css`.
- `app/`: módulos de IA, memoria, servicios, archivos y herramientas; estudiar sus dependencias antes de cambiarlos.
- `requirements.txt`: dependencias Python. `Procfile`: arranque con Gunicorn de `app.main:app`.
- `tests/stonks-rendering.cjs`: prueba de regresión con Node y Playwright, introducida en 31.3.19. Intercepta la red y utiliza respuestas simuladas.
- `README_V*.md`: documentación histórica; no sustituye al código actual de main. Los archivos de backup tampoco son la base de desarrollo.

## 3. Versionado

- `VERSION`, `VERSION.txt` y `app/VERSION.txt` deben coincidir siempre.
- Cada cambio de producto publicado debe incrementar la versión conforme a la versión indicada en la tarea. Si falta la versión objetivo, aclararla antes de publicar, sin inventarla.
- La interfaz debe mostrar la versión correcta: revisar etiquetas, información lateral y registros de inicialización, además de los archivos VERSION.
- Una tarea explícitamente documental que ordene mantener la versión no la incrementa ni modifica código funcional. La incorporación de este archivo conserva 31.3.19.
- Al incrementar versión, actualizar las expectativas de versión de los tests cuando corresponda, sin debilitar sus comprobaciones. El test de Stonks original contiene una expectativa explícita de 31.3.19.

## 4. Preservación y baseline de ZAR Stonks

No eliminar ni degradar funcionalidades salvo orden explícita. Estudiar dependencias, llamadas, estado persistido y contratos API antes de modificar una función. Preferir cambios mínimos y localizados a reescrituras grandes.

Mantener como baseline funcional:

- Alpaca Paper; Live trading desconectado hasta orden explícita.
- Motor autónomo Paper en servidor, independiente de que la ventana Stonks esté abierta, con ciclo aproximado de 5 segundos.
- Sincronización automática de UI y reconciliación de posiciones y órdenes.
- Risk, límites, pausa, revocación y kill switch.
- Position Lifecycle y Position Management.
- Capital animado y auditoría.
- Dashboard y chat de Stonks.
- Backtesting, estrategias, órdenes y Carteras & API.

Cerrar la UI debe detener sus temporizadores cuando corresponda, sin detener el motor autónomo de servidor.

## 5. Seguridad de trading y secretos

- Paper-first. Nunca activar trading Live automáticamente.
- Ningún cambio puede saltarse Risk, pausa, revocación o límites; comprobar tanto cliente como servidor.
- Las pruebas automáticas nunca deben ejecutar operaciones reales. Las pruebas de órdenes deben usar mocks, simulación o Paper según corresponda; no enviar órdenes Paper a una cuenta conectada sin autorización específica para esa prueba.
- No usar credenciales reales en fixtures. No incluir secretos ni API keys en commits, logs o respuestas.

## 6. Validación antes de publicar

Ejecutar automáticamente las comprobaciones relevantes para el cambio y los tests existentes. Para cambios funcionales, cubrir:

1. Sintaxis Python de los archivos de la aplicación; por ejemplo, `python -m compileall -q app`.
2. Sintaxis JavaScript, incluidos scripts inline y archivos externos. `node --check` sirve para archivos JS; el test de Stonks comprueba también los scripts inline con `vm.Script`.
3. Tests existentes y `node tests/stonks-rendering.cjs` desde la raíz. Requiere Node, Playwright y Chromium disponible; `ZAR_TEST_BROWSER` permite señalar el ejecutable. Si se usan dependencias del entorno, configurar su resolución sin incorporar rutas personales al código.
4. IDs HTML duplicados relevantes, errores JavaScript e inicialización de Stonks.
5. Renderizado real del DOM generado: estructura y cierres HTML; `display`, `visibility`, `opacity`, `height`, `min-height`, ancho, `overflow` y `z-index`. El dashboard no debe quedar oculto ni colapsado.
6. Apertura, cierre y reapertura de Stonks; sincronización de UI.
7. Chat abierto y cerrado sin tapar ni romper el dashboard.
8. Position Management presente y operativo, incluidos controles y guardado de configuración con APIs simuladas.
9. Coincidencia de los tres VERSION, versión objetivo y versión visible en UI.
10. Revisión de `git diff`, `git diff --check` y diff staged antes del commit; excluir cambios ajenos y secretos.

El test actual cubre escritorio a 1920×1080 y 1440×900 con APIs simuladas: no demuestra conectividad real con Alpaca ni despliegue correcto. Si se toca diseño móvil, validar también móviles y documentar limitaciones existentes.

Para tareas exclusivamente documentales sin cambios funcionales ni de versión, validar contenido, alcance, diff y conservación de VERSION; no es necesario ejecutar pruebas de trading o de navegador sin relación con el cambio.

Si falla una prueba crítica, NO hacer push: corregirla o informar claramente del bloqueo. No omitir silenciosamente pruebas, rebajar aserciones para obtener éxito ni presentar pruebas simuladas como validación en producción.

## 7. Git y publicación

Cuando la tarea indique explícitamente «publicar», «desplegar» o autorice commit y push:

1. Trabajar sobre main actualizado y preservar cualquier trabajo del usuario.
2. Implementar únicamente lo solicitado.
3. Actualizar la versión indicada, salvo excepción documental explícita, y validar el estado final.
4. Revisar diff y añadir solo los archivos de la tarea.
5. Hacer commit con el mensaje solicitado o uno descriptivo si no se especifica.
6. Hacer `git push origin main` sin pedir confirmación intermedia si las validaciones pasan.
7. Confirmar el SHA remoto y que origin/main contiene los cambios y la versión esperada.

No hacer force push. No borrar stashes. No descartar cambios del usuario sin autorización. `stash@{0}` con el trabajo local de 29.3.6 debe permanecer intacto: no recuperarlo, aplicarlo ni eliminarlo salvo nueva orden explícita. Si el push es rechazado por cambios remotos, estudiar esos cambios y volver a validar la integración; nunca forzar el remoto.

## 8. Railway

El push a main dispara el despliegue existente. No modificar configuración, secrets ni variables de Railway salvo orden explícita. Un push documental también puede activar ese flujo aunque no cambie la versión de ZAR; no alterar el despliegue para evitarlo sin autorización. Distinguir en el informe entre push confirmado y despliegue verificado.

## 9. Regresiones

Comparar la versión afectada con la última conocida como correcta y localizar la causa antes de corregir. Añadir un test de regresión cuando sea razonablemente posible. Conservar `tests/stonks-rendering.cjs` y sus comprobaciones de estructura, renderizado, chat y Position Management. No eliminar funcionalidades para ocultar una regresión.

## 10. Informe final

Después de cada publicación indicar:

- Versión, o versión conservada en una tarea documental.
- Qué se modificó y archivos principales modificados.
- Pruebas ejecutadas y resultado; pruebas no realizadas y motivo relevante.
- SHA del commit y confirmación del push a origin/main.
- Riesgos, limitaciones y cualquier prueba manual pendiente.
- Estado del despliegue solo si se ha comprobado; no equiparar push con despliegue exitoso.
