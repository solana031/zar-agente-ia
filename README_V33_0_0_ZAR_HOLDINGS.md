# ZAR 33.0.0 · Holdings + Jev + Commerce + Media + Web Agency

This release keeps the 32.1.17 Stonks/Workspace base and adds a new, isolated Holdings layer. New business runtimes are OFF by default.

## New
- ZAR Holdings dashboard with verified revenue/cost/profit ledger and Global STOP.
- Shared autonomous runtime for Commerce, Media and Web Agency.
- Jev / TypeSafe typed decision layer with zero-token deterministic fallback.
- ZAR Commerce: supplier/catalog scouting, margin checks, Shopify paid-order sync, draft product connector and confirmed supplier webhook bridge.
- ZAR Media: hook/storyboard pipeline, optional DramaClaw bridge, local vertical MP4 production through existing ZAR Studio/FFmpeg, ElevenLabs/Gemini narration, TikTok/Instagram publishing connectors.
- ZAR Web Agency: Google Maps lead discovery for businesses without a website, shareable professional demo generation, public-email candidate search, Gmail draft creation, bounded negotiation suggestions.
- Voice Pro: ElevenLabs TTS when configured; existing Gemini TTS fallback; optional faster-whisper local STT.
- Subagent graph expanded with Holdings/Jev/business agents.

## Safety / compatibility
- Stonks remains Paper-only; LIVE is not enabled.
- No supplier purchase, social publication or email send is executed merely by starting a company.
- Supplier orders and social publication require explicit confirmation. Agency creates Gmail drafts; it does not mass-send outreach.
- ChatGPT plugin connections are not reused as secrets by ZAR. ZAR connectors need their own OAuth/API variables.
- DramaClaw source is not bundled. ZAR has its own pipeline and an optional bridge to a separately hosted DramaClaw service.

## Optional Railway variables
- `JEV_API_KEY` (or `TYPESAFE_API_KEY`)
- `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, optional `ELEVENLABS_MODEL_ID`
- `ZAR_STT_PROVIDER=faster-whisper`, optional `ZAR_FASTER_WHISPER_MODEL=small` (requires `requirements-voice-extra.txt` installation)
- `SHOPIFY_SHOP_DOMAIN`, `SHOPIFY_ADMIN_ACCESS_TOKEN`, optional `SHOPIFY_API_VERSION=2026-10`
- `ZAR_SUPPLIER_CATALOG_URL`, `ZAR_SUPPLIER_ORDER_WEBHOOK`, optional `ZAR_SUPPLIER_API_TOKEN`
- `ZAR_MAPS_API_KEY`
- `TIKTOK_ACCESS_TOKEN`
- `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_IG_USER_ID`, optional `META_GRAPH_VERSION`
- optional `DRAMACLAW_API_URL`, `DRAMACLAW_CREATE_URL` for a separately hosted bridge

## Accounting
Only ledger rows marked collected are counted as collected revenue. Shopify sync marks paid orders as verified external revenue. Media/Agency revenue can be entered from a real payout/invoice/reference until their payout APIs are connected. Estimates are not counted as collected revenue.
