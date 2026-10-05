# Inferencia de NODE-02 mediante ZAR Cloud

Versión 33.2.0: coordinador y gateway preparados para el servicio `web` de
`energetic-charisma`. La activación requiere permiso global y enrolamiento
individual; la prueba real debe confirmar ONLINE y el modelo efectivo.
El chat local funciona también sin Cloud, indicando DEGRADED explícitamente.

## Proveedores existentes

`app/config.py` combina la configuración del servidor con sus variables de
entorno, que tienen prioridad. Gemini usa `GEMINI_API_KEY`; OpenAI,
`OPENAI_API_KEY`; OpenRouter conserva su modo manual/fallback existente.
`app/smart_router.py` selecciona el nivel sin un LLM adicional (salvo el adaptador
Jev opcional ya existente) y `agent._api_profiles` construye sus fallbacks.
La inspección administrativa de Cloud confirmó modo API, Gemini configurado
y modelo de configuración `gemini-3.6-flash`. El modelo efectivo se verifica
mediante la respuesta del proveedor, no solo por su configuración. No se cambian los defaults
ni se presentan sus nombres como prueba de disponibilidad de un proveedor.
El launcher local elimina claves heredadas y carga `.env.local`, sin claves de proveedores; URL y token individual se guardan solo en `.env.local`.

## Gateway aditivo y deshabilitado por defecto

`POST /v1/nodes/inference` usa el token individual y el hash persistido del
coordinador. Requiere `ZAR_NODE_INFERENCE_ENABLED=1` en Cloud y permiso
`inference_allowed` por nodo. Pausar/revocar impide la inferencia. No admite
modelos, URLs, herramientas o prompts de sistema enviados por el nodo.
El propio Cloud selecciona el modelo con el router existente y restringe este
endpoint en modo auto a economy/balanced, incluyendo el fallback economy de
OpenAI. En los modos manuales API/OpenRouter respeta el modelo elegido en Cloud.

Solo texto: máximo 6000 caracteres de entrada, 512 tokens de salida, dos
intentos/proveedores, 5 peticiones/minuto y 100/24 h por nodo, una simultánea.
Son límites técnicos de solicitudes/tokens, no un presupuesto monetario exacto.
Gemini 3 Flash usa thinking mínimo para conservar salida útil dentro de 512
tokens; una respuesta truncada no se presenta como éxito. Parámetro oficial:
[OpenAI compatibility de Gemini](https://ai.google.dev/gemini-api/docs/openai#thinking).
HTTPS verifica certificados y rechaza redirects en nodo y proveedor. La
autenticación bearer explícita impide heredar credenciales de `.netrc`. El gateway
no ejecuta herramientas ni usa memoria/cuentas de usuarios Cloud.

Los request IDs se deduplican, con cuotas/cache persistidas en el volumen actual.
Se guarda el hash del prompt, no el prompt completo; el texto de respuesta sí
se conserva para evitar repetir/billing al reintentar un ID exitoso. Errores de
proveedores nunca se devuelven en bruto. Claves configuradas y token del nodo
se redactan antes de persistir o devolver el texto. No se devuelve configuración
con claves. La autorización afecta también a las respuestas cacheadas; recuperarlas no
consume otra petición de proveedor.

`ZAR_NODE_CHAT=1` activa el cliente solamente en el launcher local; se ignora en
Railway. La sesión identifica NODE-02 y distingue el lugar del chat del lugar de
la inferencia. Usa identidad persistente y capabilities/hardware recientes del
worker, sin sobrescribir su heartbeat. Si falta configuración: DEGRADED; fallo
de red: OFFLINE; autenticación/cuota/proveedor: DEGRADED con explicación segura.
La consulta de identidad usa hechos locales cuando no hay respuesta Cloud;
si Cloud está configurado, esa misma pregunta intenta inferencia REAL y añade
los hechos locales y el modelo efectivo. No inventa un modelo para consultas
resueltas con metadata. `ZAR_NODE_LOCAL_FALLBACK=1` permite Ollama existente de
forma opcional; no instala modelos ni utiliza Codex como proveedor.
El chat de producción conserva su ruta actual.

## Activación segura en Railway

Único paso de autenticación manual:
`.local/railway-cli/node_modules/.bin/railway login`.

Luego verificar proyecto/servicio/production/volumen/dominio de EXACTAMENTE
`energetic-charisma` y el destino de la integración GitHub antes de cualquier
push. No usar `aware-serenity`. El despliegue propuesto añade el coordinador de
la fase anterior y este gateway, con tablas/campos aditivos y sin modificar
Stonks ni trasladar claves. Publicar solo tras validación, con la versión que
corresponda.

Enrolar NODE-02 mediante `scripts/node-enroll.py` y el descriptor de hash enviado
por el canal administrativo seguro a `scripts/node-provision.py enroll`, como
se documenta en README_ZAR_DISTRIBUTED_NODES.md. No copiar tokens en el chat.
En Cloud habilitar la variable global y conceder el permiso específico:

```sh
python scripts/node-provision.py inference-enable --node-id d8ee5a76-2a0b-43f8-aca5-a09b1d840b14
```

`inference-disable` revoca solo ese permiso; `revoke` invalida todo el nodo.
Reiniciar web/worker locales para cargar el token de `.env.local` y ejecutar
`.venv/bin/python scripts/node-inference-check.py`. Solo un resultado ONLINE con
modelo efectivo demuestra la inferencia Cloud; DEGRADED no la demuestra.

## Pruebas

Tests dirigidos: `tests/test_node_inference.py`, `tests/test_smart_router.py` y
las regresiones de coordinador, Holdings y Stonks. Las pruebas del contrato de
proveedor usan fixtures aislados; no pretenden validar una API real.
La prueba final `scripts/node-inference-check.py` llama al chat HTTP real en
localhost, sin mocks; resultado en `.local/test-results/node-inference-real.json`.
No hay trades, publicaciones, generación DramaClaw, cambios destructivos ni
claves nuevas de proveedores.
