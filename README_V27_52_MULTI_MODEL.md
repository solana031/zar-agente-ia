# ZAR v27.52 — Multi-Model Architecture

This release centralizes Gemini model selection by capability.

- General ZAR brain: Gemini 3.8 Flash by default (explicit ZAR_API_MODEL still overrides).
- Voice transcription: Gemini 3.5 Transcribe.
- Live voice: Gemini 3.8 Live (configured for the next Live implementation).
- TTS: Gemini 3.1 Flash TTS Preview (configured for the next native TTS implementation).
- Image: Gemini 3.1 Flash Image / Gemini 3 Pro Image.
- Video: Veo 3.1 / Veo 3.1 Fast.
- Music: Lyria 3.5.

The media model IDs are centralized now; existing local Studio workflows remain intact until each native generation endpoint is wired and tested individually.

The central “Hola, soy Zar” greeting has also been removed from the web UI.
