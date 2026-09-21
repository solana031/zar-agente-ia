# ZAR v29.1.2 — Voice Transcription Fix

- Fixes Gemini 3.5 Transcribe responses where the transcript is returned in `audioTranscription.text` instead of a normal `text` part.
- Keeps the multimodal Gemini fallback.
- Preserves all ZAR v29.1.1 functionality.
