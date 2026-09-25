# ZAR v30.10.28 — Mobile scroll + floating actions

- Mobile conversation is the actual touch-scroll surface.
- Added sufficient bottom scroll room so the latest message can be moved fully above the fixed composer.
- ZAR logo/home identity belongs to the same scroll surface and leaves through the top while scrolling.
- Hora / Recordar / Correo are floating pills and no longer occupy conversation flow.
- “Aprendizajes activos” is a smaller floating pill above the composer.
- Bottom scrolling is retried across animation frames to account for dynamic response height.
