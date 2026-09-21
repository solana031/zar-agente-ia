# ZAR v27.36 — Adaptive UX

## UI
- Right contextual rail is now a fixed overlay on desktop: it no longer consumes a permanent grid column.
- Collapsed rail is only 46px wide; expanded rail is 340px and shows complete controls without horizontal scrolling.
- Desktop no longer reuses the mobile drawer.
- Added Focus Mode (`Ctrl+Shift+F`) to hide navigation rails and maximize the chat workspace.
- Added Command Palette (`Ctrl+K`) with quick access to core ZAR capabilities.
- Preferences for rail/focus mode persist in localStorage.

## Design principles applied
- Keep the user in control.
- Make capabilities and connection state visible.
- Reduce persistent UI chrome and reserve workspace for the main task.
- Provide efficient correction/navigation shortcuts.
- Use explicit confirmation for consequential external actions already enforced by existing workflows.

References consulted: Microsoft generative AI UX guidance, Microsoft Human-AI Interaction Guidelines, Google Cloud conversational agent design guidance, Google Cloud Gemini personalization/memory guidance, and Microsoft guidance for agentic system transparency and human approval.
