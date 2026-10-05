# Nodos distribuidos de ZAR

Entrega local preparada y validada; no hay conexión REAL con producción todavía.
Railway CLI responde `Unauthorized`. Sin push ni deployment. Versión conservada:
33.1.3; 33.2.0 queda pendiente de validar Cloud → NODE-02.

## Contrato y seguridad

- El Flask existente registra el coordinador. El worker independiente hace poll
  HTTPS saliente cada 5 s, verifica TLS y rechaza redirects. No abre puertos del
  Mac. HTTP solo está permitido en loopback para pruebas.
- NODE-02 conserva `d8ee5a76-2a0b-43f8-aca5-a09b1d840b14` en
  `.local/node/worker.sqlite3`. Cloud conserva nodos/jobs/eventos bajo
  `ZAR_DATA_DIR/coordinator/coordinator.sqlite3`, en el volumen que ZAR ya exige.
  No se cambian volúmenes. SQLite está destinado al único proceso Gunicorn actual,
  no a múltiples réplicas Cloud.
- Cada nodo tiene un token aleatorio de 256 bits, únicamente en `.env.local`
  (0600, ignorado por Git). Cloud guarda SHA-256, nunca el token. No aparece en
  HTTP, UI ni logs. No procede de contraseñas, sesión, proveedores o Railway.
  Revocar invalida ese nodo y cancela sus asignaciones; no permite rotación o
  reenrolamiento silenciosos.
- El enrolamiento requiere provisionar UUID/nombre/hash mediante la CLI Cloud de
  confianza. `/v1/nodes/enroll`, `/v1/nodes/poll` y `/v1/jobs/<id>/claim` requieren
  autenticación individual, independiente de la contraseña del servidor web.
- `/api/nodes` y `/api/node-jobs` requieren una cuenta Google autenticada cuyo
  email esté explícitamente en `ZAR_NODES_ADMIN_EMAILS`. Las escrituras usan CSRF
  y comprobación de Origin. No hay administrador por defecto. El launcher local
  permite administración en loopback; ese permiso no opera en Railway.
- Estados: ONLINE, OFFLINE (30 s), BUSY, PAUSED, REVOKED. Holdings muestra NODOS
  ZAR, CPU/RAM, sistema/arquitectura, versiones, uptime/heartbeat, capabilities,
  job/progreso, resultado/error y PAUSAR/REANUDAR/REVOCAR, también en móvil.
- Solo se anuncian capacidades detectadas. `coding-agent` permanece deshabilitado.
  `dramaclaw-local` requiere respuesta de su API local: solo un GET, sin generación.
- Jobs allowlisted: `node-info`, `diagnostics`, `file-sha256`, `workspace-summary`.
  No hay shell arbitrario. Los archivos deben estar dentro de `node/inputs`, sin
  escapes por enlaces simbólicos y con máximo 64 MiB. La selección respeta
  disponibilidad, capacidades, carga, coste conocido y prioridad; un coste
  desconocido no satisface un límite de coste.
- Timeout de 5–600 s; IDs deduplicados y resultados persistentes. Pausar impide
  nuevos claims. Reiniciar marca el trabajo iniciado/reclamado como INTERRUPTED.
  Una desconexión corta conserva el job; más de 60 s marca sus asignaciones
  INTERRUPTED, sin repetir acciones. Poll/consulta/claim aplica los timeouts;
  el siguiente poll comunica cancelaciones. Resultados tardíos no sobrescriben
  estados terminales. Para reintentar se crea deliberadamente otro job.

## Arranque local

Usando el entorno y launcher ya existentes en este Mac:

```sh
.venv/bin/python scripts/local.py web
.venv/bin/python scripts/node-worker.py run
```

URL: http://127.0.0.1:8765/ . No iniciar otra instancia del worker activo: el lock
lo impide. Sin URL/token, su conexión Cloud indica NOT_CONFIGURED.

## Conectar después de autenticar Railway

1. Ejecutar `.local/railway-cli/node_modules/.bin/railway login`.
2. Verificar EXACTAMENTE `energetic-charisma`, su servicio ZAR, production,
   volumen y dominio HTTPS. Nunca usar defaults ni `aware-serenity`. Comprobar
   el destino de la integración GitHub antes de hacer push. GitHub autenticado
   como `solana031` no equivale a Railway autenticado.
3. Configurar el email Google administrador en `ZAR_NODES_ADMIN_EMAILS`, preparar
   33.2.0 y publicar solo tras validación. Comprobar health/version, Holdings,
   Stonks Paper y `/v1/nodes/health` después del deployment.
4. En el Mac ejecutar `scripts/node-enroll.py --cloud-url ORIGEN_HTTPS` con la
   `.venv/bin/python`. Conserva/genera el token local y emite únicamente el
   descriptor UUID/nombre/hash. Enviar ese descriptor por stdin a
   `python scripts/node-provision.py enroll` en una sesión SSH autenticada al
   servicio exacto. Railway SSH admite flags explícitos:
   `--project UUID_VERIFICADO --service SERVICIO_VERIFICADO --environment production`.
   Comprobar que conserva stdin; alternativamente transmitir solo el descriptor
   por ese canal administrativo. Nunca copiar ni mostrar el token.
5. Reiniciar el worker, comprobar ONLINE/heartbeat y crear UN job inocuo con
   `python scripts/node-provision.py test-job` en Cloud. Comprobar BUSY → progreso
   → resultado → ONLINE. Consultar el resultado mediante la API administrativa.

NODE-01-WINDOWS reutiliza el contrato con UUID/token propios y
`ZAR_NODE_NAME=ZAR-NODE-01-WINDOWS`; RAM y lock tienen implementaciones portables.
Ese PC no se ha configurado. Los cambios anteriores de las integraciones y la
instalación local se conservan aparte del commit de nodos.

## Pruebas dirigidas

```sh
.venv/bin/python -m pytest -q tests/test_node_worker.py tests/test_node_scheduling.py tests/test_distributed_nodes.py tests/test_holdings_v33.py tests/test_stonks_automaton.py tests/test_stonks_live_readonly.py
.venv/bin/python scripts/node-loopback-check.py
NODE_PATH=.local/browser/node_modules PLAYWRIGHT_BROWSERS_PATH=.local/browser/browsers node tests/nodes-ui.cjs
NODE_PATH=.local/browser/node_modules PLAYWRIGHT_BROWSERS_PATH=.local/browser/browsers node tests/stonks-rendering.cjs
NODE_PATH=.local/browser/node_modules PLAYWRIGHT_BROWSERS_PATH=.local/browser/browsers node tests/local-smoke.cjs
```

35 tests Python pasan. El HTTP loopback ejecuta realmente node-info con claves y
SQLite de prueba aislados; resultado sin secretos en
`.local/test-results/node-loopback.json`. No demuestra conexión Cloud. El panel
se prueba con página/CSS completos y APIs simuladas en 1440×900 y 390×844.
Stonks conserva sus aserciones y pasa en siete tamaños; solo se añaden los assets
nuevos a su transporte simulado. No se envían órdenes Paper ni Live.
Limitación previa: el preflight de lifecycle de Stonks falla si `engine_last_run`
es null; no se modifica Stonks en esta fase.
