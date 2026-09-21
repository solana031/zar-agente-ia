# ZAR v29.3.3 — Button Reliability + Hover Boundary Fix

Incremental update over v29.3.2.

- Fixes the Deep Research HTML/JavaScript quoting issue that could stop the main inline script from parsing.
- Keeps a capturing fallback for existing `onclick` handlers, including dynamically-created buttons.
- Prevents bottom quick/home actions from moving/enlarging on hover and visually crossing into the composer.
- Places the UI patch inside the document body instead of after `</html>`.
- Synchronizes VERSION and VERSION.txt to 29.3.3.
