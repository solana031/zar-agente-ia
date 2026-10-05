# ZAR-NODE-02-MAC · entrega local

Consolidación local del 5 de octubre de 2026. Versión **33.2.0** en los tres
VERSION. Base remota observada: `983efb31ae2758cdb6cd9136998476df17cc4b59`.
Se preservaron los tres commits locales `20f64e0`, `116f3d9` y `38fcdc2`,
sin pull, reset, push ni despliegue. Los apartados de instalación y validación
histórica describen la preparación anterior; no constituyen pruebas actuales
ni autorización para publicar en Railway.

## Estado comprobado al consolidar

- ZAR activo en `http://127.0.0.1:8765/`, health 33.2.0; worker activo,
  lock ocupado y heartbeat reciente, sin jobs activos.
- La configuración privada existente **ya contiene** URL HTTPS Cloud y token
  de nodo. No se crearon, modificaron ni publicaron credenciales. El heartbeat
  persistido informa ONLINE y el endpoint local conserva una inferencia previa
  ONLINE (Gemini). No se repitió inferencia ni se verificó Cloud directamente.
- DramaClaw API/editor no escuchan en 8780/8781; runtime instalado, servicio
  detenido. No se arrancó ni se ejecutaron generaciones.
- Jev NOT_CONFIGURED; Codex instalado pero ejecución de nodo DISABLED.
  Conway compilado, prueba `--version` correcta, sin autorización de ejecución.
- Stonks: Paper, sin credenciales/conexión Alpaca; pausado y revocado, motor
  autónomo apagado, Live bloqueado. GET local self-test: 20/20, cero órdenes.
- Auditoría de archivos candidatos: sin patrones de tokens reales, claves
  privadas o rutas personales; `.env.local` y SQLite con permisos 0600 e
  ignorados. `.local`, `.venv`, `.bootstrap-venv` y cachés quedan fuera de Git.
- Verificación actual: 76 tests Python y 6 subtests; regresiones Stonks y Media,
  smoke localhost GET, sintaxis Python/JS y diff. La expectativa antigua de
  Media se actualizó de 33.1.3 a 33.2.0 sin reducir la aserción.
- No se repitió el smoke del editor detenido ni los ensayos HTTP de fases
  anteriores. No se hicieron trades, peticiones LLM, publicaciones ni pagos.

## Estado encontrado en código e historial

| Componente | Implementado antes de esta tarea | Pendiente real |
|---|---|---|
| DramaClaw | 33.1.3 / `983efb3`: cliente oficial `/api/v1`, pipeline Media, checkpoints durables, reconciliación, revisión, MP4 y publicación con confirmación; tests con mocks | Instalar servicio y configurar modelos/voz; demostrar generación autorizada, cuotas y publicación real |
| Jev | 33.0.0 / `de35b62`: `app/jev_decision.py`, endpoint TypeSafe real, decisiones tipadas utilizadas por Commerce y Web Agency; fallback explícito | API key y validación real del proveedor; el fallback no es Jev |
| Automaton | 32.1.16 / `1eafd33`: estado y métricas Paper del bucle Stonks propio | No existía runtime Conway; el módulo original dice expresamente «inspired by», sin wallet ni shell |
| Holdings | 33.0.0 y 33.1.0 / `de35b62`, `683164e`: empresas, ledger, políticas, runtime de servidor, Media, Commerce, Agency y Sites | Conectores/cuentas reales; escrituras, pagos, despliegues y publicaciones conservan sus políticas |
| Media | 33.1.1 / `63ce494` y 33.1.3: interfaz directa y pipeline real DramaClaw | No hay evidencia de un vídeo pagado producido o publicado en producción |
| Workspace | 32.1.0–32.1.15: builders y herramientas Google reales, especialistas, confirmaciones persistentes e idempotencia | OAuth local y verificación de documentos reales; el nodo añade solo procesamiento de archivos de entrada |
| Stonks | Motor Paper de servidor, Risk, Lifecycle, Position Management, reconciliación, chat, backtesting, shadow, aprendizaje, Automaton Mode y Live bloqueado | Conectividad Alpaca no validada aquí; no se enviaron órdenes Paper ni Live |

El historial atribuye commits a `solana031` y al bot de actualización desde ZIP;
no permite atribuir con certeza cada línea a una sesión anterior de Codex.
Se distingue el código existente de las afirmaciones históricas de los README.
La referencia histórica a otro proyecto Railway no se utilizó ni se modificó.

## Arranque en este Mac

Desde la raíz del repositorio, cada proceso en su terminal:

```sh
.local/dramaclaw-venv/bin/python scripts/dramaclaw-local.py
.venv/bin/python scripts/dramaclaw-editor.py
.venv/bin/python scripts/local.py web
.venv/bin/python scripts/local.py worker run
```

ZAR: **http://127.0.0.1:8765/**. Health: `/health`.
DramaClaw API: **http://127.0.0.1:8780/api/v1/config**.
Editor oficial DramaClaw: **http://127.0.0.1:8781/**; acceso solo loopback.
Configurar modelos/voz posteriormente en Settings del editor oficial, con claves
autorizadas. CE guarda esa configuración en su settings.db local; no inventar
un token estático de autenticación CE. El editor se instaló con el pnpm-lock
oficial, sin scripts de instalación ni descarga de pesos de modelos.
Ctrl+C detiene cada proceso. No se instaló un servicio de autoarranque de macOS.
Si los procesos ya están activos, no lanzar una segunda instancia en esos puertos.

El launcher local sirve la interfaz sin exigir Google OAuth, exclusivamente en
loopback. Google sigue desconectado y sus herramientas mantienen controles y
confirmaciones. Este comportamiento no modifica `app/main.py` ni el login de
producción. El launcher limpia credenciales heredadas y utiliza únicamente la
configuración explícita de `.env.local` y su almacenamiento local aislado.

`.env.local` está ignorado por Git, con permisos 0600; la plantilla pública es
`.env.local.example`. La configuración creada apunta a la API DramaClaw de
loopback. Ese era el estado inicial; la configuración Cloud/token ya está presente en la consolidación. No se copiaron tokens de Google,
Railway, Alpaca, Codex ni proveedores. Jev está NOT_CONFIGURED; un fallo de
proveedor produce DEGRADED y fallback identificado, sin autoridad de ejecución.

## Instalación y compatibilidad

- Mac Intel x86_64, macOS 13.7.8, 4 CPU lógicas, 8 GiB RAM.
- Python del sistema 3.9.6 no se modificó. Python 3.12.15 está en `.local/python`;
  ZAR usa `.venv`; DramaClaw usa `.local/dramaclaw-venv`; uv está aislado en
  `.bootstrap-venv`. Requirements de producción intactos; restricciones locales
  en `requirements-local.txt` y `constraints-dramaclaw-mac.txt`.
- DramaClaw oficial `a35f758e9c8821ba130bdd731ac88c8f52e7c566`, paquete 2.0.6,
  código intacto en `.local/upstream/dramaclaw`. Cognee 1.0.5 instalado. El lock
  requiere ajustes Intel admitidos por los rangos del proveedor: cryptography
  46.0.7, LanceDB 0.24.0, PyLance 0.22.0 y cbor2 5.8.0. No se usa un sustituto
  de Cognee. La API y el contrato de ZAR se comprobaron mediante GET reales.
- Conway oficial `d8f816881fd24b6f5e3d616e59edec387a447667`, runtime 0.2.1,
  instalado y compilado en `.local/upstream/automaton`; binding better-sqlite3
  probado con una DB en memoria. Adapter separado `app/conway_adapter.py`.
  Solo se ejecutó `--version`, nunca `--setup`, `--provision` ni `--run`.
- Node 22.23.3 y Codex CLI 0.160.0 existentes. ZAR web no necesita npm.
  El editor DramaClaw sí utiliza Node/Vite; pnpm 11.5.0 está aislado en
  `.local/build-tools` y su store bajo `.local`.
- Playwright 1.48.2 / Chromium 130 aislados: Playwright más reciente no admite
  este macOS. Este navegador se usa para pruebas locales, no para browsing
  general de Internet. FFmpeg 7.1 de imageio y FFprobe 9.0.2 Intel en
  `.local/bin`; no se instalaron globalmente.
- No torch, extras `world`, modelos de Hugging Face ni pesos GPU instalados.
  No se necesitan Redis/Postgres/Celery externos para DramaClaw CE: backend
  inline y almacenamiento local. Sus paquetes declarados no implican servicios
  auxiliares arrancados.

Inventario exacto local: `.local/install-manifest.json`,
`.local/installed-zar.txt`, `.local/installed-dramaclaw.txt`.
Conservar `.local/data`, `.local/node` y `.local/dramaclaw-data` al actualizar;
no forman parte del código publicado.

Fuentes oficiales:
[DramaClaw](https://github.com/dramaclaw/dramaclaw/tree/a35f758e9c8821ba130bdd731ac88c8f52e7c566),
[TypeSafe HTTP API](https://docs.typesafe.ai/api),
[Conway Automaton](https://github.com/Conway-Research/automaton/tree/d8f816881fd24b6f5e3d616e59edec387a447667),
[distribuciones FFmpeg](https://ffmpeg.org/download.html).

## Nodo y orquestación preparada

Identidad persistente: `d8ee5a76-2a0b-43f8-aca5-a09b1d840b14`, nombre
**ZAR-NODE-02-MAC**. SQLite `.local/node/worker.sqlite3`, permisos 0600.
Lock de proceso evita dos workers; recuperación de RUNNING a QUEUED solo bajo
ese lock. Los handlers actuales son de lectura, repetibles tras interrupciones.

```sh
.venv/bin/python scripts/local.py worker status
.venv/bin/python scripts/local.py worker enqueue '{"kind":"diagnostics"}'
.venv/bin/python scripts/local.py worker get ID
.venv/bin/python scripts/local.py worker cancel ID
.venv/bin/python scripts/local.py integrations
.venv/bin/python scripts/node-loopback-check.py
```

El worker es independiente de Flask y no abre ningún puerto. Heartbeat cada
5 segundos, cola persistente, prioridad, progreso, resultados y cancelación.
Los archivos deben estar bajo `.local/node/inputs`, máximo 64 MiB; no acepta
shell, paths externos, credenciales, trading, generación ni publicación.
Handlers habilitados: `diagnostics`, `file-sha256`, `workspace-summary`.

Capacidades de herramientas detectadas: python, node, browser, filesystem, git,
media-processing y workspace-processing. No todas tienen todavía un handler
remoto: el heartbeat publica también la lista exacta de handlers autorizados.
Coste por job desconocido, sin inventar tarifa. Coding-agent se informa como
capacidad opcional **DISABLED**; no se anuncia como ejecutor remoto disponible.

`app/node_coordinator.py` se registra en la aplicación principal mediante
`register(app)`. El harness independiente sirve para pruebas aisladas. API actual:

| Endpoint | Autoridad |
|---|---|
| POST `/v1/nodes/poll` | Token individual de nodo: heartbeat, reports, entrega de jobs, ACK y cancelaciones |
| GET `/api/nodes` | Admin: recursos/capacidades, ONLINE si heartbeat <30 s; OFFLINE en otro caso |
| POST `/api/node-jobs` | Admin: job autorizado, prioridad y techo opcional de coste |
| GET `/api/node-jobs/<id>` | Admin: progreso/resultado persistente |
| POST `/api/node-jobs/<id>/cancel` | Admin: cancelación; worker la recoge en el siguiente poll |

Transporte saliente HTTPS, validación TLS normal, Bearer individual, redirects
desactivados. HTTP se permite solo en loopback para pruebas. Tokens admin/nodo
distintos; un nodo no puede modificar jobs de otro. El scheduler considera
heartbeat reciente, capacidad, concurrencia, carga normalizada, coste conocido
y prioridad de jobs. `ZAR_NODE_CREDENTIALS_JSON` permite enrolar UUIDs Cloud,
NODE-01 y NODE-02 con tokens distintos cuando existan; no inventa otros nodos.
Los costes reportados son estimaciones del nodo enrolado, no una contabilidad.

El ensayo HTTP real de loopback utiliza tokens efímeros en memoria y un
coordinador temporal. En la preparación inicial el worker no tenía conexión; en la consolidación ya existe configuración privada y heartbeat ONLINE.
Para activar posteriormente: desplegar coordinador autorizado en
energetic-charisma, configurar URL HTTPS y credenciales individuales. No hace
falta exponer el Mac ni Tailscale para el protocolo pull. Si se elige Tailscale
o WebSocket, conservar los mismos contratos/políticas.

Limitaciones: un job asignado a un nodo offline permanece asignado para evitar
doble ejecución; no hay failover automático de efectos externos. Solo handlers
de lectura están autorizados. El coste, el enrolamiento de NODE-01 y la selección
real entre máquinas requieren validación posterior. El Mac necesita permanecer
encendido y despierto; no se cambiaron políticas de suspensión.

## Codex y Conway: límites actuales

`app/coding_capability.py` detecta el CLI y prepara una invocación read-only,
ephemeral, sin configuración de usuario, tarea acotada y checkout dedicado bajo
`.local/workspaces`. Requiere opt-in y aprobación explícita local; no ejecuta
el proceso ni lee/guarda credenciales. La autorización no se recibe desde jobs
Cloud. Para habilitar ejecución futura faltan un runner con timeout/cancelación,
salida acotada y una política de aprobación vinculada a cada tarea.

Conway real permanece NOT_CONFIGURED y detenido. Su diseño incluye wallet,
provisión, herramientas y gasto; antes de arrancar se necesita servicio aislado
con autoridad de herramientas/red/gasto controlada y credenciales autorizadas.
El adapter actual demuestra la instalación del runtime real y su versión, no
ejecuta su bucle ni lo conecta al broker. Automaton Mode de Stonks se conserva
íntegro y no se presenta como Conway.

## Validación histórica y posible publicación futura

Pruebas dirigidas Python: 52 tests y 6 subtests, con HTTP/socket externos
bloqueados. Cubren node persistence, recovery, cancelación activa/encolada,
auth, aislamiento de nodos, replay/ACK, prioridad/coste/carga, contratos
DramaClaw, Media, Holdings, Jev degradado, Codex y Stonks Live read-only.
Regresión Stonks: siete viewports de escritorio/móvil, DOM, chat, Position
Management, cierre/reapertura/sincronización y cero errores JS. Prueba Media:
brief íntegro, revisión, progreso, estabilidad MP4 y confirmación de publicación
con APIs simuladas. El briefing largo se inserta por evento DOM para evitar
el timeout de input del Chromium antiguo; las aserciones de visibilidad,
editabilidad y contenido permanecen, igual que los fills de texto ordinario.
Smoke HTTP/UI real localhost: health, Holdings, Media, Workspace y Stonks
Paper, solo GET y sin tráfico externo del navegador. Protocolo HTTP loopback
real: heartbeat/ONLINE/job/result/cancelación/reinicio. Python y JS válidos;
VERSION conservados; `git diff --check` limpio.
Editor oficial DramaClaw: DOM visible y cero errores JS, con todas las
escrituras y peticiones externas bloqueadas durante la prueba.

```sh
.venv/bin/python -m pytest -q tests/test_node_worker.py tests/test_node_scheduling.py tests/test_optional_integrations.py tests/test_dramaclaw_client.py tests/test_media_dramaclaw.py tests/test_holdings_v33.py tests/test_stonks_automaton.py tests/test_stonks_live_readonly.py
NODE_PATH=.local/browser/node_modules PLAYWRIGHT_BROWSERS_PATH=.local/browser/browsers node tests/stonks-rendering.cjs
NODE_PATH=.local/browser/node_modules PLAYWRIGHT_BROWSERS_PATH=.local/browser/browsers node tests/media-dramaclaw-ui.cjs
NODE_PATH=.local/browser/node_modules PLAYWRIGHT_BROWSERS_PATH=.local/browser/browsers node tests/local-smoke.cjs
NODE_PATH=.local/browser/node_modules PLAYWRIGHT_BROWSERS_PATH=.local/browser/browsers node tests/dramaclaw-local-smoke.cjs
```

Pendiente: claves Jev, OAuth Google y proveedores/voz DramaClaw en su configuración
oficial local; prueba pagada solo con autorización nueva; contener y autorizar
runtime Conway; enrolar nodos reales y tokens. No se validó producción/Railway,
Alpaca conectado, documentos Google reales, generación pagada o publicación.
No se ejecutaron suites enormes, trades, compras, pagos ni publicaciones.

Propuesta futura: revisar estos adapters y el coordinador, definir versión
objetivo, desplegar únicamente en energetic-charisma con almacenamiento
persistente y tokens individuales; mantener DramaClaw privado/autenticado,
Conway aislado y Stonks Paper. No incluir `.local`, `.venv` ni credenciales en
esa publicación. Push y despliegue requieren una nueva instrucción explícita.

## Archivos de esta entrega

Modificados: `.gitignore`, `app/jev_decision.py`, `tests/conftest.py`,
`tests/stonks-rendering.cjs`, `tests/media-dramaclaw-ui.cjs`.

Nuevos: `.env.local.example`, `requirements-local.txt`,
`constraints-dramaclaw-mac.txt`, este README;
`app/node_worker.py`, `app/node_coordinator.py`, `app/node_scheduling.py`,
`app/coding_capability.py`, `app/conway_adapter.py`;
`scripts/local.py`, `scripts/dramaclaw-local.py`,
`scripts/dramaclaw-editor.py`, `scripts/node-loopback-check.py`;
`tests/test_node_worker.py`, `tests/test_node_scheduling.py`,
`tests/test_optional_integrations.py`, `tests/local-smoke.cjs`,
`tests/dramaclaw-local-smoke.cjs`.

Instalación/configuración/estado local ignorados: `.venv`, `.bootstrap-venv`,
`.env.local`, `.local` y cachés `.vite`. En aquella entrega inicial no se modificaron `app/main.py`,
`app/templates/index.html`, `app/stonks_automaton.py`, `requirements.txt`,
`Procfile` ni los tres VERSION.

## Clasificación de la consolidación

Código: validación Jev, adapters opcionales Codex/Conway y launchers DramaClaw.
Dependencias declarativas: `requirements-local.txt`, `constraints-dramaclaw-mac.txt`.
Pruebas: optional integrations, smoke localhost/editor, ajuste Media UI y
expectativa VERSION Media. Documentación: este archivo.
Ejemplo público: `.env.local.example` ya incluido en commits anteriores.
Privados/runtimes: `.env.local`, `.local` (datos, tokens, runtimes, dependencias,
reportes), `.venv`, `.bootstrap-venv`, bases SQLite y cachés permanecen ignorados.
No publicar hasta recibir una instrucción explícita. Antes de conectar de nuevo,
aclarar el enrolamiento ya existente y revisar URL/identidad/permisos sin rotar
ni duplicar credenciales; validar luego un job de lectura autorizado.
