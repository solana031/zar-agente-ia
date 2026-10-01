# ZAR v31.3.47 — Stonks Zero-Token Data Plane

## Objetivo
Separar la supervisión continua de Stonks del uso de modelos de IA. El worker puede seguir ciclando cada ~5 s para seguridad/lifecycle, pero señales, noticias y razonamiento no se recalculan ni escalan a un LLM si no hay cambios relevantes.

## Nuevo Data Plane
- Cache de señales técnicas por ventana de barra cerrada.
- Cache de noticias públicas con TTL independiente.
- Event Router determinista para detectar cambios relevantes.
- AI Gate cerrado por defecto: marca candidatos, pero no llama a Gemini/OpenAI.
- Telemetría de ciclos 0 tokens, cache hits/misses, eventos y llamadas IA evitadas.
- Estimación de tokens evitados frente a una arquitectura ingenua de 1 llamada LLM por ciclo. La estimación es orientativa y usa `ZAR_STONKS_TOKEN_BASELINE_PER_CYCLE` (1200 por defecto).

## Self-Test Agent
Subagente determinista que valida en runtime:
- Paper-only.
- Router 0 tokens.
- IDs de agentes únicos.
- Arquitectura crítica completa.
- Data Plane activo.
- AI Gate cerrado.
- Shadow nunca crea órdenes.
- Modo de ejecución válido.
- Guard de Position Lifecycle en Paper automático.

No usa Codex ni LLM y no crea órdenes.

## Uso eficiente de recursos
- Worker de seguridad/lifecycle: ~5 s.
- Señales: solo cuando puede existir una nueva barra cerrada; mercado cerrado usa cache más larga.
- Noticias: TTL ~5 min.
- UI: lee estado local cada 5 s; no llama a un LLM.
- IA: 0 llamadas automáticas en esta versión.

## Seguridad
- Live continúa desconectado.
- Shadow continúa en 0 órdenes.
- Paper sigue pasando por Decision + Risk.
