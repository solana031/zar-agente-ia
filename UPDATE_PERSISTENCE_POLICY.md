# ZAR update persistence policy — v31.3.27+

Updates must modify application code/assets only.

Never overwrite, reset, delete, package or migrate persistent runtime state unless an explicit migration is deliberately requested and reviewed.

Protected persistent state includes, at minimum:
- /data and user-scoped persistent storage
- memory databases, embeddings and indexes
- conversation/history state
- users/, backups/, jobs/
- saved Studio/audio/video projects
- ZAR Stonks Paper portfolio, positions, signals/history and metrics
- OAuth/session/runtime tokens stored outside source control
- *.sqlite, *.sqlite3 and *.db runtime databases

A release ZIP must contain source code and required static assets only. Persistent state belongs to the mounted Railway volume/runtime storage and survives code releases.
