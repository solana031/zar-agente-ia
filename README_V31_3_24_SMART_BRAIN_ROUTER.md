# ZAR 31.3.24 — Smart Brain Router

ZAR incorpora un enrutador determinista de IA que decide el cerebro antes de llamar a un modelo, sin gastar tokens en esa decisión.

## Cerebros

- Local: Ollama (`OLLAMA_MODEL`, por defecto `qwen3:8b`) para tareas ligeras cuando el backend puede alcanzarlo.
- Economy: Gemini 3.5 Flash-Lite para conversación y tareas rutinarias.
- Balanced: Gemini 3.8 Flash para herramientas, contexto y complejidad media.
- Strong: GPT-5.6 Terra para código, análisis y planificación exigente cuando `OPENAI_API_KEY` está configurada.
- Max: GPT-5.6 Sol para tareas largas o de máxima exigencia cuando `OPENAI_API_KEY` está configurada.
- OpenAI economy fallback: GPT-5.6 Luna.

## Ahorro

La clasificación usa reglas locales y cuesta 0 tokens API. Las rutas tienen fallback automático entre Gemini y OpenAI. Ollama se usa solo si el servidor de ZAR puede comprobar que está accesible; en Railway, `127.0.0.1` no es el PC del usuario.

## Configuración

Variables nuevas opcionales:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `ZAR_OPENAI_ECONOMY_MODEL`
- `ZAR_OPENAI_STRONG_MODEL`
- `ZAR_OPENAI_MAX_MODEL`
- `ZAR_GEMINI_ECONOMY_MODEL`
- `ZAR_GEMINI_BALANCED_MODEL`
- `ZAR_AUTO_LOCAL_MAX_CHARS`
- `ZAR_LOCAL_PROBE_TTL`

El modo predeterminado para instalaciones nuevas es `auto`. Una variable `ZAR_PROVIDER` existente sigue teniendo prioridad para preservar despliegues ya configurados.
