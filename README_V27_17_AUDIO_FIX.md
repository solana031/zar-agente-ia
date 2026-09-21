# ZAR v27.17 — Audio Studio playback fix

- Audio preview endpoint uses conditional/range-capable Flask `send_file`.
- Generated WAV metadata is persisted (`rendered_file`, `rendered_at`).
- Studio audio player explicitly reloads the generated source and waits for browser metadata/canplay before reporting the result.
- UI reports generated duration and BPM and gives a useful error if the browser cannot open the generated audio.
- Existing Forms, Voice, YouTube and Studio functionality is preserved.
