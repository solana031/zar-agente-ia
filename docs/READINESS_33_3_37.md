# ZAR — Product Readiness Review / RC 33.3.37

Inspección inicial: 2026-10-11. Cierre del candidato: 2026-10-12. Este documento distingue el código existente, las pruebas aisladas y las comprobaciones de producción. La presencia de una ruta o una credencial no demuestra que una integración esté conectada. El candidato se prepara sobre la base publicada 33.3.36; la publicación y su SHA final se registran al cerrar la revisión.

## Estado previo verificado

- El diagnóstico Git encontró historias distintas de `zar-current` y `origin/main`, con contenido de producto coincidente. La rama de trabajo `codex/readiness-33-3-37` se creó desde `origin/main`, después de conservar las instrucciones/configuración locales en una copia con hashes y un stash nombrado. Se restauraron los cambios locales preservados sin publicar la reconciliación. El stash histórico permanece intacto.
- El coordinador comprobó por HTTPS `/health`: HTTP 200, `ok`, versión **33.3.36**, antes de los cambios del candidato.
- El proyecto Railway canónico **energetic-charisma** presentaba despliegue `SUCCESS` para el commit abreviado `fdb828a` al inspeccionarlo. No equivale a que el candidato nuevo ya esté desplegado.
- El servicio web de respaldo **aware-serenity** figuraba `SLEEPING`, con branch de auto-deploy nula. No debe desplegarse ni modificarse.
- Propiedad técnica: `solana031@gmail.com`. Identidad operativa preferente para servicios: `zaragente031@gmail.com`. No se reasignan cuentas a partir del nombre de una variable.

## Arquitectura y límites de la evidencia

El inventario inicial por AST encontró 128 módulos Python y 239 decoradores de rutas (211 en `app/main.py`). `main.py` tenía 6488 líneas e `index.html` 6388. Los números describen la base inspeccionada y crecen al añadir las correcciones. Flask registra además blueprints de Browser, Company Workspace y YouTube y rutas de Nodes, Studio Music, Holdings Workflows/Orchestration y Stripe.

`Procfile`/`Dockerfile` arrancan Gunicorn con un worker y cuatro threads. El servidor inicia los motores Stonks/Holdings al importar `main.py`; importar la aplicación sin aislamiento no es una prueba inocua. El motor Paper y el runtime de empresas tienen ciclos independientes de las ventanas del navegador.

La mayor parte del estado usa JSON por `ZAR_DATA_DIR/users/<scope>`; Memory/Knowledge añade SQLite por usuario. `user_scope.py` transporta la identidad con ContextVar. Las conexiones OAuth se cifran mediante `oauth_vault.py`. Browser usa un proceso Chromium separado y almacenamiento cifrado; Files mantiene índice y archivos fuera del código. El DAW nuevo guarda proyectos por usuario y procesa audio en el navegador. Audio/Video legacy empleaban raíces globales: el aislamiento de esos caminos requiere resolución explícita, sin borrar material histórico.

La navegación inicial registra 22 workspaces en `app/static/workspace-tabs.js`, con iframes del mismo origen. Hay módulos adicionales dentro de Studio, Control y Orchestration. Abrir un workspace conserva el DOM de los demás; cerrar elimina su iframe. Esto conserva formularios al alternar, pero exige pausar el polling de los documentos ocultos.

Estados: `VERIFIED` indica una prueba ejecutada con alcance indicado; `READY` indica capacidad local lista con requisitos explícitos; `CONNECTED` exige evidencia reciente de la API y cuenta correctas; `PARTIAL` identifica cobertura o flujo incompleto; `OPTIONAL`, `ACTION_REQUIRED`, `ERROR` y `DISABLED` conservan su significado literal. Las tablas siguientes son un mapa estático **PARTIAL**, no una certificación general de producción. “Suite existente” no significa “suite pasada en este candidato”.

## Matriz completa del producto

La ruta UI común es `/`; `/?zar_workspace=<id>` abre una subapp independiente. Las funciones nombradas pertenecen a `app/templates/index.html`, salvo indicación. Las referencias por función se mantienen válidas aunque cambien las líneas durante la revisión.

| Módulo / estado inicial | Ruta / UI | Backend / API | Persistencia | Responsive / tests existentes | Integración externa y verificación pendiente |
|---|---|---|---|---|---|
| Home / PARTIAL | `/`, hero, dock, rail, composer | `main.home`, `/api/state` | Preferencias localStorage; sesión | `general-ui.cjs`, `responsive-audit.cjs`; inspección visual de seis tamaños pendiente | Estado del servidor; no exige proveedor para mostrar la UI |
| Chat / PARTIAL | Home composer y mensajes | `/api/chat`, `/api/jobs/<id>`, agent/model_router/tools | jobs, memory/context scoped | release-3310/11/12 y general-ui | Modelos configurados; verificar respuesta sin consumo de pago no autorizado |
| Conversations / PARTIAL | workspace `conversations`, `showConversations` | `/api/conversations`, búsqueda, restore, deletion-review | JSON de conversaciones scoped | release-339 y general-ui | Ninguna para leer archivos locales; borrar exige revisión |
| Memory / PARTIAL | workspace `memory`, `showMemory` | `/api/memory/*`, knowledge/memory3 | SQLite y JSON scoped | architecture/release suites | Embeddings opcionales; no confundir índice local con conexión de modelos |
| Learnings / PARTIAL | workspace `learning`, `ZARSkills.open` | `/api/learning/*`, `/api/skills/*` | JSON y jobs scoped, worker reanudable | general-ui, subapp-consolidation | Investigación/modelos según tarea; probar pausa/reanudación aislada |
| Files / PARTIAL | workspace `files`, `showFiles`, file-memory.js | `/api/files`, upload/preview/download/patch/share/delete/reindex | índice y binarios scoped | `test_file_preview_formats.py`, files-layout, UI release suites | Compartir exige identidad/destino y confirmación; no publicar archivos de prueba |
| PDF / PARTIAL | visor de artifacts y Files | artifact_engine.create → document_renderer.render_pdf | PDF como artifact/file scoped | `test_document_renderer.py`, file-preview-formats | Renderer local ReportLab; verificar todos los callers y lectura visual del PDF |
| Workspace / PARTIAL | workspace `workspace`, company-workspace.js | `/api/company-workspace`, company_knowledge | JSON con revisiones, fuentes, historia y conflictos | company-workspace UI/Python, company-knowledge | Extracción local usa evidencia real; material sin OCR/análisis permanece pendiente |
| Google Account / PARTIAL | workspace `google`, identity-provisioning.js | `/connect/google`, `/api/google/services/check`, identity_center | OAuth cifrado y capacidades scoped | identity-336, identity-refresh, connector-policy | Verificar cada API; OAuth general no acredita ocho servicios activos |
| Gmail / PARTIAL | workspace `gmail`, mensajes y revisión de email | `/api/gmail/recent`, `/api/gmail/message/<id>`, identity_mail | contexto/borrador/confirmación scoped | mail-sender, identity-336, release-3312 | Lectura separada de envío. Ningún email real durante QA |
| Drive / PARTIAL | acciones Workspace/chat y exportación de artifacts | google_workspace.drive_*, `/api/workspace/verify-writes` | archivos remotos + referencias locales | business-workspace/identity/release suites | Verificar acceso de la cuenta exacta y un archivo autorizado |
| Docs / PARTIAL | exportación de informe/tarea | google_workspace + artifact_engine.workspace_export | documento remoto y evidencia en Holdings | identity/release suites | Scope o acceso Drive no demuestra que Docs funcione |
| Sheets / PARTIAL | exportación de informe y workflows de negocio | google_workspace.sheets_* | hoja remota con provenance | company/workflow/identity suites | No escribir en hojas reales durante QA |
| Slides / PARTIAL | exportación de artifacts | google_workspace.slides_* | presentación remota | identity/release suites | Verificar documento autorizado; no inventar CONNECTED |
| Forms / PARTIAL | herramienta en chat/Workspace | google_workspace/forms tools | formulario remoto | cobertura indirecta tools/identity | Superficie adicional encontrada; no declarar operativa sin API |
| Calendar / PARTIAL | workspace `calendar`, showMobileCalendar, formulario | `/api/calendar/month`, `/upcoming`, nuevo `/create`; google_calendar.py | Google Calendar del scope actual | `test_calendar_create.py` (17 casos PASSED); interacción UI pendiente de cierre | POST requiere CSRF, confirmed=true, fecha válida, scope de escritura y JEV; cero eventos reales enviados |
| Contacts / PARTIAL | workspace `contacts`, búsqueda/favoritos | `/api/contacts`, google_contacts/contact_resolver | Google + contexto local | general-ui; tests de resolución mail | Cuenta Google y permiso Contacts; nunca sustituir por contactos ficticios |
| Tasks Google / PARTIAL | `showTasks`, Control | `/api/tasks`, google_tasks | tareas remotas, lectura | general-ui | Scope tasks.readonly; no prometer edición si el permiso no la admite |
| Research / PARTIAL | `showResearch`, tareas semánticas | `/api/research/*`, research_agent/deep_research | jobs, informes y fuentes scoped | release-3310/11/12 | Fuentes web reales; fallo de búsqueda no permite fabricar evidencia |
| Semantic Tasks / PARTIAL | semantic-tasks.js, task-results.js | `/api/semantic/tasks/*` | planes, pasos y outputs scoped | release-3310/11/12 | Research → informe → destinatario → borrador → confirmación → envío |
| Maps / PARTIAL | workspace `maps`, maps-ui.js | `/api/maps/search`, maps.py | sin estado de negocio permanente | mobile-map-menu, general-ui | Google Maps según configuración; search y Places se prueban por separado |
| Browser / PARTIAL | workspace `browser`, zar-browser.js | GET/POST `/api/browser`, zar_browser/browser_worker/browser_network | actor por usuario, sesión cifrada, Files para descargas | browser-guards, workspace-tabs | URL/red pública filtrada; CAPTCHA, 2FA, alta y términos son Human Action |
| Studio / PARTIAL | workspace `studio`, editor IMAGEN/AUDIO/VÍDEO | `/api/studio/command`, studio_agent | según editor | studio-music, general-ui, responsive-audit | No rediseñar DAW; validar herramientas existentes |
| Image Editor / PARTIAL | canvas, filtros, crop/rotate/export | procesamiento navegador y Files | estado canvas; exportación Files | general-ui y revisión focalizada | No dependencia externa para edición local |
| Studio Audio / DAW / PARTIAL | music-studio/engine/midi.js | `/api/studio/music/projects` GET/PUT | JSON scoped; WAV/MIDI navegador | studio-music.cjs, music-midi.cjs, test_studio_music.py | Micrófono requiere permiso; salida real local sin proveedor pagado |
| Audio legacy / PARTIAL | fallback renderAudioEditor, bases y FX | `/api/studio/audio/projects/*`, audio_studio.py | raíz histórica global al iniciar revisión | cobertura UI indirecta | Pendiente resolución aislamiento scoped; preservar audio existente |
| Video / PARTIAL | editor multimedia Studio | `/api/video/projects/*`, video_creator.py, FFmpeg | raíz histórica global al iniciar revisión | general-ui, release UI | Render local; publicación externa confirma identidad y destino |
| Clipper / PARTIAL | workspace `clipper`, media-production.js | `/api/holdings/media/*`, media_company/projects/surface | proyectos, checkpoints y MP4 scoped | media-dramaclaw, dramaclaw-client, clipper-preview, workspace-tabs | DramaClaw/RelayClaw/Cloudinary separados; comprobar MP4 previo antes de warning |
| Sites / PARTIAL | workspace `sites`, sites-native.js | holdings workflows, site_projects/sites_native | proyecto y artefactos scoped | test_sites_native, workspace-tabs, sites-live (online separado) | Preview privado; publicar exige confirmación. AdSense/dominio no implican monetización |
| Reselling / PARTIAL | workspace `dropshipping`, commerce-agency.js | commerce_workspace/company/adapters, Shopify | niches/products/suppliers/orders en Holdings | test_commerce_agency, commerce-agency UI, workflows | No inventar tienda/proveedor/pedido; proveedor real + autorización externa |
| Web Agency / PARTIAL | workspace `agency`, leads/propuestas | agency_crm/mail/events, web_agency | leads, propuestas, assets scoped | commerce-agency suites | Email/cobro con confirmación; propuesta PDF usa artifact_engine |
| Wallet / PARTIAL | workspace `wallet`, treasury-account.js | business_orchestration, financial_events/provider, relayclaw_usage_sync | balances/ledger/reservations/approvals scoped | financial-events/adapters, treasury-limits, capital-identity | Unidades/quota no son dinero; cobros reales requieren evidencia y deduplicación |
| Holdings / PARTIAL | workspace `holdings`, `showHoldings` | `/api/holdings/state`, company_runtime | state.json scoped + ledger | holdings-v33, business-orchestration | Revenue/cost/profit derivados de eventos; no usar métricas TEST como ventas |
| Stonks / PARTIAL | workspace `stonks`, dashboard/chat/risk | 47 rutas baseline `/api/stonks/*` | estado, auditoría, aprendizaje y engine owner | 21 suites Python Stonks + stonks-rendering.cjs | Alpaca Paper únicamente; ninguna orden real/Paper conectada en QA |
| Automaton / PARTIAL | Stonks capital/automaton | `/api/stonks/automaton*` | capital/reservas/estado controlado | automaton, readiness, preflight | Live bloqueado; movimientos internos no acreditan fondos reales |
| Orchestration / PARTIAL | workspace `orchestration`, clusters/inspector | `/api/subagents/*`, holdings orchestration | vista scoped + estados de runtime | scalable/adaptive/business-orchestration | Nodos reflejan workers/estados; no confundir catálogo con actividad |
| Nodes / PARTIAL | nodes.js, Control | `/api/nodes`, `/v1/nodes/*`, node_coordinator | coordinator store + jobs/inference | distributed-nodes, worker/inference/scheduling | Enrollment/host real; no inferir conexión por configuración |
| JEV / PARTIAL | decisiones en Orchestration/workflows | jev_decision.evaluate/gate | decisiones/audit scoped | holdings, identity, release-3312 | Política local separada del proveedor TypeSafe opcional |
| Human Actions / PARTIAL | workspace `human`, identity center | identity_center.queue/view/operate | acciones deduplicadas por servicio/acción | identity-336, workspace-tabs | SERVICE/ACCOUNT/BLOCKER/WHY/EXACT STEP/CONTINUE; no completar KYC artificialmente |
| Settings / PARTIAL | openZarSettings, configuración/voz/tema | `/api/config`, config.py | config de servidor + localStorage | general-ui y regresiones nuevas | Fallos de guardado deben visibles; no mostrar éxito falso |
| Control / Time / Weather / PARTIAL | Control workspace y widgets | `/api/control/health`, `/api/studio/time`, `/weather` | estado consultado; reloj local | general-ui, responsive-audit | Weather necesita red/ubicación; permiso denegado no es error de app |
| YouTube / PARTIAL | Google Account, Clipper/Video publishing | youtube_auth/youtube_publish/social_publish | OAuth específico, publicación y métricas | identity-336, media/optional integrations | Probar canal de la cuenta exacta; no subir/publicar en QA |
| TikTok / PARTIAL | integración y revisión Clipper | social_publish | IDs/estado publicación scoped | media/optional/release suites | Token/creator capabilities; privacidad no debe caer a PUBLIC por defecto |
| Instagram / PARTIAL | integración y revisión Clipper | social_publish | IDs/estado publicación scoped | media/optional suites | Cuenta/proveedor/permiso; publicación real requiere confirmación |

## Integraciones: evidencia exigida

| Servicio | Estado honesto sin prueba fresca | Comprobación necesaria / Human Action |
|---|---|---|
| Google Gmail/Calendar/Contacts/Drive | PARTIAL | OAuth de la cuenta actual + respuesta API por servicio |
| Docs/Sheets/Slides/Forms | PARTIAL | Leer un objeto autorizado o ejecutar una escritura previamente autorizada; un scope no basta |
| YouTube | PARTIAL | API devuelve canal e identidad; upload capability separado de publish probado |
| DramaClaw | PARTIAL | Health + proyecto/job real + archivo de salida reproducible; no generar con coste sin aprobación |
| RelayClaw | PARTIAL | Registro proveedor con ID estable, moneda y cantidad verificadas; cuotas/tokens sin conversión supuesta |
| Cloudinary | PARTIAL | Prueba de cuenta/asset permitido; ninguna subida de material personal solo para QA |
| ElevenLabs | OPTIONAL | Credencial/voz/capacidad reales; generación con coste necesita autorización |
| Lovable existente | PARTIAL | Propiedad técnica conservada; verificar proyecto existente; no crear una cuenta duplicada |
| Shopify | ACTION_REQUIRED si sin tienda verificada | Tienda real, proveedor, producto y permisos exactos; no fabricar storefront |
| Stripe | PARTIAL | Cuenta/API/webhook verificados; no es una cuenta bancaria de tesorería por sí sola |
| AdSense | PARTIAL | OAuth readonly, accounts state, sitio real y aprobación; KYC/tax/banco/términos humanos |
| TikTok / Instagram | PARTIAL | Identidad y capacidades del proveedor; confirmación de publicación aparte |
| Revolut Business | ACTION_REQUIRED sin cuenta/API verificada | Identidad empresarial, cuenta elegible, permisos API y reconciliación; KYC/tax/banco humanos |
| Wise Business / otro financiero | OPTIONAL | Evaluar documentación/cuenta elegible antes de elegir; no asumir disponibilidad por nombre comercial |

## Bugs localizados y correcciones del candidato

1. **Calendar submit enviaba a una ruta inexistente** (`/api/calendar/create`). Se implementó el contrato, CSRF de sesión, `confirmed` booleano explícito, validación local de título/fechas/descripción/location, revisión JEV/global stop y comprobación de scope OAuth de escritura. `location` se conserva. Los errores del proveedor se sanitizan y no se reintentan silenciosamente. Se conserva el formato ISO y el horario de Madrid del flujo existente. `tzdata` condicional Windows corrige la disponibilidad local de ZoneInfo.
2. **Polling duplicado en workspaces**: el baseline repetía Skills cada 5 s y Learning cada 1,5 s en todos los iframes, incluso ocultos. Diez pestañas podían generar alrededor de 520 peticiones/minuto solo por estos dos ciclos. Corregido: un único propietario del polling global, sin peticiones desde iframes ocultos; guardas contra solapamiento y pausa del refresco de Holdings/tareas inactivas.
3. **Ajustes daba éxito tras fallar `/api/config`**: corregido en `saveZarSettings`; el error permanece visible y el reintento se verifica mediante UI.
4. **Google mostraba estados sobreestimados**: `state()` asociaba OAuth global a Gmail/Calendar y ocho servicios de fallback. Corregido: OAuth se presenta como autorización y Cuenta Google caduca la prueba independiente a los diez minutos.
5. **Sites preview/publicación y Human Actions**: corregidos límites de scope, confirmación booleana/JEV antes de publicar y agrupación por cuenta/servicio conservando el historial original; regresiones offline pasadas.
6. **Audio/Video legacy compartían almacenamiento**: corregido mediante almacenamiento por scope y prueba explícita del propietario legacy. Se verifican creación/listado y denegación entre dos usuarios en ambos editores; los archivos históricos se conservan. El worker de vídeo hereda el contexto del propietario.

## QA ejecutada y estrategia de cierre

- Inspección estática con AST, rutas, dependencias, persistencia, contratos UI/API, polling y renderizadores. No se leyó ni publicó ningún valor secreto.
- Calendar backend: **17 pruebas pasadas** en `tests/test_calendar_create.py`, proveedor mocked. Se comprueban CSRF, confirmación ausente/falsa, títulos/fechas inválidos, fin anterior al inicio, location, global stop, scopes readonly, identidad actual, error sanitizado sin reintento, día completo y fechas legacy Madrid. No prueban conectividad Google real.
- Inventario baseline: 400 métodos test en 49 `test_*.py`, 34 suites Playwright `.cjs` y scripts `release-*` adicionales. La colección completa puede incluir parametrización y nuevas regresiones, por lo que el número ejecutado será distinto.
- `tests/conftest.py` usa DATA/JOB/CONFIG temporales y prohíbe `requests.Session.send` y conexiones socket. Suites Stonks compilan funciones desde AST para evitar arrancar el motor conectado.
- Dependencias QA instaladas en `.local/readiness-python-deps` al faltar pytest y varias librerías del requirements en Python local. No se incorporan al producto ni se versionan. En Windows las ACL del sandbox obligaron a ejecutar las pruebas fuera de él; el bloqueo de red del fixture permanece activo.
- Suite Python completa: **485 passed + 49 subtests passed**. Tras añadir dos casos de integración de almacenamiento, la suite focalizada de finanzas/media completa pasó **6/6** (cuatro ya incluidos y dos nuevos).
- Playwright: usar APIs interceptadas, fixtures marcadas TEST y Chromium; validar botones, formularios, preview, cancelación, modal, guardar, alternar y reabrir. Los tests online `sites-live.cjs` y `production-media-qa.cjs` se ejecutan solo con destino leído y permitido.
- Viewports objetivo: 1366×768, 1440×900, 1920×1080, tablet 768×1024 y móviles 390×844, 393×852, 412×915. 21 workspaces × 7 resoluciones: **147 recorridos PASS**, apertura/cierre, dimensiones, cancelación/confirmación de Calendar y fallo/reintento de Ajustes; cero excepciones JS. Se guardan 154 capturas locales contando Home. Revisión visual directa de Home, Wallet, Calendar, Sites, Clipper, Orchestration y Browser; las capturas restantes están disponibles para ampliar la revisión humana.
- Producción RC: el SHA, despliegue, `/health`, versión, logs y navegación posteriores al push se registran en el informe de entrega y en `.local/readiness-release-result.json`. La prueba HTTP baseline 33.3.36 no certifica el nuevo candidato.

## Acciones humanas y límites reales

CAPTCHA, 2FA, KYC, datos legales/fiscales/bancarios, aceptación de términos, pagos, compras, publicación pública y acciones irreversibles conservan intervención humana. Un formulario de onboarding completado localmente no marca una cuenta conectada. No se envían emails, no se publican videos/sitios, no se compran dominios ni se colocan órdenes Paper en cuentas conectadas como parte de los tests.

La matriz anterior conserva el inventario inicial. VERIFIED en las pruebas locales no equivale a conexión externa ni a prueba exhaustiva de todos los botones del producto.


## Evidencia de cierre del RC

- Versión: **33.3.37**, los tres VERSION y las etiquetas/cachés de la UI coinciden. Base remota comprobada: `fdb828a2cacf7305fa84e56134ce503a1262ddfd`; no se reescribe historial.
- Git: rama `codex/readiness-33-3-37` basada en origin/main. `zar-current`, stash histórico y stash nombrado de preservación permanecen. AGENTS.md, `.kilo/`, `kilo.json`, artifacts y otros untracked personales quedan fuera de este release.
- Corregidos además: respuestas tardías Calendar/Contacts/Files; breadcrumb/categoría Files; Browser elimina captura/texto/controles anteriores al redactor o cerrar; límites financieros cuentan SETTLED y se revalidan antes de ejecutar; pedidos seleccionan negocio reselling; métricas separadas por moneda y exclusión TEST; Sites no muestra despliegue solicitado como publicación lista; previews privados de Sites/Agency exigen procedencia; token local de Node restringido por ACL Windows.
- UX: navegación de módulos duplicada retirada; ajustes móvil abre controles reales; Home conserva nombres legibles y personalización, sin tarjetas vacías; Wallet usa formulario en columnas en escritorio y una columna en móvil; workspaces opacos.
- Python: sintaxis de **129 módulos** verificada. Suite completa y regresiones arriba. Fixtures corregidos con contratos vigentes: selección de remitente, modal ZarUI, contexto Flask, estados JEV local/hosted y versión vigente; no se quitaron comprobaciones funcionales de Stonks.
- Playwright PASS: `stonks-rendering` (7 tamaños, Risk/Position Management, chat, cierre/reapertura), `workspace-tabs-3318` (4 tamaños, sin duplicados, formularios conservados, restore de sesión), `studio-music` (4 tamaños, notas/FX/proyectos/WAV/MIDI), `music-midi`, `company-workspace-ui` (5 tamaños), `files-layout-3315`, `mail-sender-3320`, `identity-refresh-3325`, `commerce-agency-ui`, `media-dramaclaw-ui`, `business-orchestration-ui`, `readiness-ui`, `readiness-browser`.
- Todas estas pruebas de UI interceptan APIs. No acreditan envío real de email, publicación, cobro, compra, trading conectado ni inferencia pagada. Ninguno se ejecutó durante QA.

## Producción observada antes de publicar

- Canonical health HTTP 200 y 33.3.36. Railway energetic-charisma SUCCESS, main fdb828a. Backup aware-serenity web SLEEPING, auto-deploy sin rama; no se visitó ni modificó su servicio.
- Google operativo: APIs Gmail/Drive/YouTube respondieron con la cuenta `zaragente031@gmail.com` el 11 de octubre; la evidencia es temporal y se vuelve a verificar antes de usar. Docs/Sheets/Slides conservaban evidencia anterior, no se certifican como recién comprobados.
- Sitio real conservado: [Guías de productividad digital](https://web-production-a9565.up.railway.app/holdings/site/gu-as-de-productividad-digital-f1b9bd/), HTTP 200, title y descripción presentes, robots y sitemap HTTP 200 con siete páginas. Contenido legal/contacto y aprobación AdSense requieren revisión humana antes de monetizar.
- Clipper: MP4 existente `70d97071aec345f7` cargado por navegador con `readyState=4`, duración **5 segundos**. Se conservan también los proyectos ERROR y PAUSED; no se ocultan ni se fabrican nuevos renders.
- RelayClaw: se pulsó sincronización real en Wallet. Resultado **ACTION_REQUIRED**, sin importes monetarios verificables; cero cargos inventados. No se convirtió cuota a EUR ni se declaró completo el histórico limitado por la API.
- AdSense: scope específico ausente; cuenta/aprobación sin verificar. Shopify/Stripe/TikTok/Instagram/ElevenLabs: sin credenciales/conexión probada en ZAR. Lovable conserva identidad técnica; no se duplica cuenta.

## Proveedor financiero y acciones humanas concretas

1. **AdSense / zaragente031@gmail.com**: autorizar scope de lectura, comprobar cuenta y sitio existentes; aportar términos/datos fiscales/bancarios/KYC personalmente cuando se soliciten. Continuar con la verificación AdSense de ZAR. No hay ingresos acreditados.
2. **Tesorería / identidad empresarial real**: comprobar elegibilidad/cuenta Revolut Business y completar acceso/KYC/consentimiento; después conectar API READ con certificado/OAuth. PAY continúa deshabilitado. No se eligió ni abrió una cuenta por inferencia.
3. **Shopify / proveedor / redes sociales**: confirmar tienda y cuentas operativas existentes, OAuth y proveedor real. Guardar credenciales únicamente en el servidor canónico y usar CONTINUAR/VERIFICAR. No migrar cuentas personales ni aceptar planes/términos automáticamente.
4. **RelayClaw**: aportar una factura o respuesta oficial que identifique importe y moneda, o acceso API a ese dato. El contador de uso solo no acredita un cargo.

Wise Business no debe tratarse como sustituto automático para tesorería española: su documentación limita los personal API tokens y excluye financiación de transferencias y extractos de saldo salvo seis países, entre los que no está España. [Wise: personal API tokens y limitaciones](https://docs.wise.com/guides/developer/auth-and-security/personal-api-token). La integración Stripe existente en ZAR es de cobros; no demuestra una cuenta bancaria o Stripe Treasury elegible. La elección final depende de entidad, jurisdicción y acceso API comprobado.

## Pendiente real

La consolidación no habilita integraciones ausentes. Quedan verificación humana de cuentas/consentimientos, monetización y contenido legal del sitio, prueba autorizada de flujos externos de coste/envío/publicación, revisión visual manual de todas las capturas y un crawl exhaustivo de cada botón/estado con datos reales. No se presenta ZAR entero como producto certificado ni se sustituyen esos límites por métricas ficticias.
