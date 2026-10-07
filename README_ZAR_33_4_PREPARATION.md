# Preparación local de integraciones (sin release)

La versión canónica se conserva en **33.3.0**, SHA
`996bfa7d5826a0136727205294c8627c77f2bc79`. Estos cambios no autorizan
publicación, despliegue, compras, modelos de pago ni operaciones de trading.

## DramaClaw

ZAR mantiene el cliente REST y sus checkpoints del pipeline oficial completo:
brief → proyecto → ingest → episodios → guion → identidad/storyboard → frames/
vídeo → narrator sample → audio → composición → descarga de MP4 → preview.
La publicación conserva la confirmación existente. No se reconstruye el motor.
Upstream instalado: `dramaclaw/dramaclaw`, pin del contrato
`a35f758e9c8821ba130bdd731ac88c8f52e7c566`; paquete `supertale-ce` 2.0.6.
Un health correcto sólo acredita acceso a la API, no modelos ni generación.

Todas las mutaciones y el worker de producción pasan por el control de costes.
Las llamadas con coste desconocido se bloquean **antes** de enviar la petición.
Eso también bloquea editar/regenerar remotamente; guardar un briefing local,
consultar trabajos y previsualizar un MP4 existente no requieren generación.

El runtime oficial documenta estos modos:

* Official: DC Key de https://relayclaw.cdnfg.com, modelos RelayClaw; puede costar.
* Custom: NewAPI y canales/modelos para texto, embedding, imagen, vídeo y audio;
  credenciales del proveedor seleccionado y potenciales costes.
* Local + Official Hybrid: ComfyUI/workflows/modelos instalados para vídeo local;
  **Hybrid no garantiza** que el resto del pipeline sea gratuito.
* Edge TTS es gratuito pero usa red; no es un fallback offline.
  CosyVoice/DashScope y fal/IndexTTS2 requieren configuración y pueden costar.

ElevenLabs es opcional: `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, modelo
opcional `ELEVENLABS_MODEL_ID`. Se utiliza la API oficial ya integrada para un
sample, nunca el router de voz con fallback automático a Gemini. La nueva ruta
`media_narrator` ofrece una voz macOS instalada (`say`) bajo sandbox sin red.
Un sample local **no convierte** la etapa de audio posterior de DramaClaw en
gratuita. La generación completa y los modelos concretos siguen pendientes.

## Jev / TypeSafe

Upstream oficial: https://docs.typesafe.ai/introduction/quickstart.
Credencial: **TYPESAFE_API_KEY**, creada en https://console.typesafe.ai.
`JEV_API_KEY` sigue como alias compatible; no contiene una clave inventada.
Contrato: HTTPS `POST https://api.typesafe.ai/v1/systemone`, Bearer,
`model=jev-latest`, `state`, `questions`; primitivas `choice`, `score`, `noul`.

Se conserva la participación real en Smart Router cuando un proveedor puede
autorizarse: recomendación tipada → selección de modelo → respuesta de ZAR.
Una recomendación degradada nunca sustituye el router determinista. Timeout
máximo de 10 s (router 3 s), sin reintentos automáticos, validación, auditoría de
tier/fallback y hash del payload, circuit breaker persistente (3 errores, 60 s).
Las excepciones de programación no relacionadas no se esconden en el adapter.
Con presupuesto cero no se llama a TypeSafe aunque exista una credencial.

## Conway

Runtime real `Conway-Research/automaton` 0.2.1. OFF por defecto. OBSERVE sólo
ejecuta `--version` aislado. PROPOSE utiliza **PolicyEngine oficial** y su SQLite
de auditoría para evaluar propuestas, sin LLM, wallet ni ejecución de herramientas.
Sólo admite propuestas `read_file` con paths relativos no privados; se ponen en
cuarentena para revisión humana. Exec, red externa, compras, transferencias,
wallet, secretos, borrado, publicaciones y despliegue están bloqueados.

EXECUTE figura como modo bloqueado, no como falsa integración autónoma lista.
El `--run` upstream necesita inferencia y puede obtener autoridad financiera;
no está autorizado ni implementado como ejecución segura. Hace falta verificar
una inferencia gratuita, mediar cada herramienta real y aprobar una política
antes de ofrecer EXECUTE. No se configura wallet ni se provisiona Conway.

## Coding Agent / NODE-02

El worker y coordinador admiten `coding-task`/`coding-agent-local`, anunciada
sólo con opt-in local y los requisitos mínimos. DISABLED por defecto;
READ_ONLY/PATCH/FULL requieren una aprobación local de un solo uso ligada al
spec completo, TTL de 5 minutos. Cloud no puede emitir esa aprobación ni
activar los modos del Mac mediante el endpoint de política de Cloud.

`scripts/automation-control.py approve-coding <spec.json>` solicita confirmación
humana local, no inicia Codex. Spec: `task`, `files`, `mode`, `tests`; sólo checks
`python-syntax`/`javascript-syntax` host-owned. El job añade `approval_id`.
El Mac requiere `ZAR_CODING_LOCAL_MODEL` y ese modelo **ya instalado** en Ollama.
Se rechazan modelos Cloud/remotos o sin evidencia de pesos GGUF locales.
No se descargan modelos ni hay fallback OpenAI/Gemini de pago.

El runner usa el **Codex CLI instalado**, `--oss --local-provider ollama`, config
ignorada y CODEX_HOME temporal sin auth. Copia únicamente objetos Git del HEAD
de main a un clon temporal limpio, verifica el mismo SHA y crea allí la
branch/worktree por tarea. Los cambios pendientes del checkout principal no
se incorporan; no hay selector de repositorios externos. El clon, worktree y
rama temporales se eliminan al finalizar, conservando resultado/diff persistidos.
No edita main. Scope exacto de archivos, bloqueo de symlinks,
secretos y metadatos Git. Herramientas de shell/web/hooks, plugins, apps, browser/computer e
integraciones autónomas de Codex deshabilitadas:
**0 comandos del modelo**; hasta 5 comandos de checks controlados por el host.
Timeout ≤300 s, cancelación/pause/revoke durante la tarea, kill switch, límites
de salida/diff y resultado persistente. Lectura/cancelación local en
`/api/integrations/coding/results/<id>` (cancelación POST con CSRF).
FULL tampoco concede commit/push/deploy.
En macOS Ventura, la excepción Seatbelt del cliente es
`(allow network-outbound (remote ip "localhost:11434"))`: permite solamente
loopback IPv4/IPv6 al puerto 11434. Otros puertos e Internet permanecen
denegados. Probes nativos comprueban conexión local, denegación de red externa,
archivos privados, escrituras fuera de scope, timeout y cancelación antes de
una tarea real; estos probes no acreditan por sí solos que Codex haya leído
archivos o completado una inferencia.

El proceso Codex recibe `CODEX_OSS_BASE_URL=http://127.0.0.1:11434/v1`, la variable
reconocida por el CLI 0.160.0. No se exporta `OLLAMA_BASE_URL` ni se habilita
DNS: el cliente usa IP numérica mientras Seatbelt expresa el filtro como
`localhost:11434`. CODEX_HOME es temporal, sin auth Cloud, y se elimina al finalizar.
El prefijo `/v1` es necesario: Codex añade `/models` y `/responses` a esta base.
Codex 0.160.0 sólo admite Responses; `wire_api="chat"` y `ollama-chat` fueron
eliminados. Su comprobación oficial de versión exige Ollama >=0.13.4.
Ollama añadió `/v1/responses` en 0.13.3, pero el ejecutable oficial
Intel 0.13.4 declara macOS mínimo 14.0, incompatible con este Mac 13.7.8.
Ollama 0.12.3 conserva `/v1/models` y Chat Completions, sin Responses. La tarea
READ_ONLY sigue sin validar: no se instala un proxy ni se ejecuta otra tarea
mientras el contrato no sea compatible. Fuentes oficiales:
https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/model-provider-info/src/lib.rs
https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/ollama/src/lib.rs
https://docs.ollama.com/api/openai-compatibility
Resultados >14 KB se resumen al coordinador y conservan íntegros en el Mac.
Los logs guardan hash/tamaño, no texto de prompts ni contenido de errores.

La versión del CLI y el sandbox se prueban realmente. Las tareas de parche se
validan con CLI/modelo simulado y **worktrees Git reales temporales**; todavía
no acreditan una tarea real de inferencia/patch del modelo local.

## Sandbox, presupuesto, UI y límites

Mac Seatbelt (`sandbox-exec`), deny-default, env sin secretos, allowlist de
ejecutables/paths, sin procesos shell; red denegada salvo Ollama loopback
127.0.0.1:11434 para coding. IPC general no permitido. Los journals SQLite
temporales de Conway son la única excepción de unlink en esa ejecución.
En plataformas sin sandbox nativo se rechaza ejecutar, no se simula aislamiento.

AI/Automation Budget persiste límites en céntimos EUR por tarea, día UTC, mes
UTC y proveedor. Todos empiezan en **0**. Reservas atómicas impiden sobrepasarlos
por concurrencia; costes inciertos y fallos no se reembolsan automáticamente.
**Un presupuesto positivo no habilita llamadas de coste desconocido**: faltan
cotizaciones verificables/topes del proveedor y mediación de cobro. No se
conectan pagos. Este control cubre estas integraciones; el chat interactivo y
el motor de riesgo de Stonks conservan sus contratos existentes.

Holdings añade siete tarjetas INTEGRACIONES / CEREBROS, estados/evidencias,
versiones, nodo, capacidades, heartbeat, costes desconocidos, requisitos y probes
sin modelos. Cloud health/protocolo se pueden probar con GET públicos sin token;
el estado del nodo se lee de heartbeats persistidos, sin enviar jobs.
Los modos/límites requieren administrador, CSRF, mismo origen y
confirmación. El kill switch de Cloud cancela coding jobs, además del local.
Cloud agrega estado/versión de Codex y Conway del heartbeat autenticado de
NODE-02 con una proyección estricta: descarta keys, wallets, argv y configuración.
Las tarjetas de esos runtimes no permiten activación remota desde Cloud.
No se anuncian nodos inventados ni una generación completa como LISTO.

Policy/audit/approvals/results residen en ZAR_DATA_DIR, fuera del código.
Runtimes, `.env.local`, wallets, bases de datos, keys y `.local` siguen ignorados.
Stonks permanece Paper; no se toca el hard lock Live ni se envían órdenes.
El smoke con datos nuevos detectó un fallo previo de preflight: heartbeat `null`
provocaba HTTP 500. Se valida su tipo y se conserva `UNVERIFIED`, nunca permiso
para operar; la regresión añadida verifica también que START no envía órdenes.
