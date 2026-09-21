# ZAR v29.1.4 — Voice transcription fix

- Fixes parsing of Gemini Interactions responses where transcription text is exposed inside `steps[].content[].text`.
- Uses the documented Gemini 3.5 Transcribe Files + Interactions flow with an audio-only input.
- Keeps Spanish (`es-ES`) verbatim transcription.
- Preserves existing GenerateContent and multimodal fallbacks.
- Preserves the rest of ZAR v29.1.3.
