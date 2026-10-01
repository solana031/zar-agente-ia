# ZAR v32.1.0 — Multi-Asset Paper + Workspace Agents

## ZAR Stonks
- Paper-only universe auto: up to 4 equities/ETF + up to 4 Alpaca crypto USD pairs.
- Prioritizes BTC/USD, ETH/USD and SOL/USD when active/tradable and reserves room for a liquid meme-style pair when available.
- Crypto data uses Alpaca crypto bars/latest trades/snapshots and remains observable 24/7; equities remain tied to the US regular-session clock.
- Shadow observes in parallel with Paper and keeps zero order authority.
- Paper Quality Guard remains in front of Decision + Risk. Crypto has an independent 3-minute cooldown and 16-entry/day-per-symbol ceiling; these are caps, not targets.
- Optional Paper scalp exit seeks at least $0.10 estimated net profit after a configurable round-trip cost/slippage buffer. It never forces an entry or guarantees profit.
- LIVE remains hard blocked.

## Workspace Pro / Multi-Agent
- Zero-token specialist router: Supervisor, Research, Visual Research, Data Analyst, Sheets Designer, Docs Designer, Slides Designer and Quality Agent.
- Durable Google Workspace confirmations: pending actions are stored both in user context and browser session so a later “sí/adelante/confirma” executes the prepared action instead of losing it.
- `sheets_upgrade_workbook`: reorganizes an existing workbook into professional tabs without deleting the original data and can add useful charts.
- Professional Docs and Slides builders, with sourced/reusable imagery support for Slides.
- `web_image_search` searches Wikimedia Commons and preserves source/license metadata.
- External/current research can be routed through web search before creating the artifact.

## Safety invariants
- No LIVE trading adapter is enabled.
- Shadow has zero order authority.
- Paper entries still require Signal → Quality Guard → Decision → Risk.
- Existing Workspace data is preserved unless deletion is explicitly requested.
