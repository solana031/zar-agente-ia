# ZAR v29.3.2 — Button Reliability + Hover Boundary Fix

- Restores reliable execution of existing `onclick` actions through a capturing button bridge.
- Covers both initial and dynamically generated buttons without replacing the underlying ZAR feature functions.
- Prevents quick/home action buttons from translating/enlarging on hover and visually crossing into the composer area.
- Keeps the composer controls above chat content and explicitly preserves pointer interaction on its buttons.
- Preserves the complete v29.3.1 feature set; this is an incremental UI reliability patch.
