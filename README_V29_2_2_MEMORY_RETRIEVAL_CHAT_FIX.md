# ZAR v29.2.2 — Memory Retrieval + Chat Stability

- Memory 3.0 ahora se inyecta explícitamente en el contexto del agente.
- Recuperación semántica + candidatos recientes como respaldo cuando embeddings no están disponibles.
- Los recuerdos recién guardados quedan disponibles para consultas posteriores aunque el embedding falle o tarde.
- Se conserva Memory 2.0 y todo lo existente en v29.2.1.
- La memoria recuperada se trata como datos, nunca como instrucciones del sistema.
- Se conserva voz, Live, TTS, archivos, Google, Studio y Control ZAR.
