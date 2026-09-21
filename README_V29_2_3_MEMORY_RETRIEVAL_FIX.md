# ZAR v29.2.3 — Memory Retrieval Fix

- Corrige un error de inicialización en `app/agent.py` que podía provocar `cannot access local variable conversation_text where it is not associated with a value`.
- La memoria recuperada se añade al contexto después de construir `conversation_text`.
- Conserva las funciones de v29.2.2: Memory 3.0, recuperación semántica, respaldo de recuerdos recientes, voz, Live, TTS, archivos, Google, Studio y Control ZAR.
