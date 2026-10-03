# ZAR 33.1.3 — DramaClaw real integration

Media uses the official `/api/v1` project/ingest/episode/script/identity/storyboard/frame/video/audio/compose/export APIs, checked against `dramaclaw/dramaclaw@a35f758e9c8821ba130bdd731ac88c8f52e7c566`. No guessed create-video endpoint or local graphic/video fallback remains.

The full master brief is persisted unchanged in the Holdings task. Each production also has a durable checkpoint under `ZAR_DATA_DIR/users/<scope>/media_jobs/`: project ID, task identifiers, current stage, submission intent and bounded revision history. Atomic writes and an OS file lock serialize each job across requests/workers. The existing Holdings runtime advances authorized jobs; refreshing the UI only reads status. Unknown submissions are reconciled against tasks/resources, never blindly submitted again. Unrecoverable ambiguity requires checking the existing DramaClaw project.

Only a confirmed composed final MP4 is downloaded (same configured origin, no redirects, MP4 signature, size bound) and exposed as a ZAR preview. Editing preserves the original brief, adds the user's instructions and explicitly starts a new revision. Editing an active/uncertain remote job is blocked. Publication requires boolean confirmation, uses a scoped signed MP4 link valid for 24 hours, persists intent before sending, and tracks the same TikTok publish ID / Reels container without recreating them. TikTok additionally requires developer-app approval and verification of the ZAR download domain.

## Variables in ZAR

- `DRAMACLAW_API_URL`: origin, or origin plus `/api/v1`. Railway internal example: `http://${{dramaclaw-api.RAILWAY_PRIVATE_DOMAIN}}:8780`.
- `DRAMACLAW_WEB_URL`: optional **authenticated, browser-accessible** editor origin. Leave unset while the editor is private; no unusable editor link is shown.
- `DRAMACLAW_API_TOKEN`: optional real Bearer credential accepted by the configured deployment/proxy. CE does not accept arbitrary static API keys; do not invent one.
- `ZAR_MEDIA_DIRECT_ONLY=1`: explicit deployment policy; Media now always fails closed without DramaClaw.
- Keep `ZAR_DATA_DIR` on the existing persistent ZAR volume. No other runtime/memory/credentials are migrated.

The existing ZAR voice router remains ElevenLabs → F5-TTS → Gemini. If ElevenLabs is configured, Media can supply a short reference sample through the official narrator-voice upload. This is a cloning reference, **not** an externally generated final narration track; DramaClaw subsequently generates episode audio through its own supported audio/model gateway. An existing narrator sample can also be configured in DramaClaw. Missing voices/models/quotas produce a visible blocked/error stage.

## Railway deployment

Reference: [official release compose](https://github.com/dramaclaw/dramaclaw/blob/a35f758e9c8821ba130bdd731ac88c8f52e7c566/docker-compose.release.yml).

In ZAR's existing `aware-serenity` project, separate private services:

- `dramaclaw-api`: `claymorelab/dramaclaw:2.0.4`, API port 8780, persistent volume `/data`. `ST_EDITION=ce`; `NOVELVIDEO_DATA_ROOT=/data`, output/state/runtime under `/data`; `NEWAPI_PROVISIONER_ENABLED=false`.
- `dramaclaw-web`: `claymorelab/dramaclaw-frontend:2.0.4`; `BACKEND_HOST=${{dramaclaw-api.RAILWAY_PRIVATE_DOMAIN}}`, `BACKEND_PORT=8780`, container port **80** (`8080` is the official compose's host port).
- No administrative gateway or public DramaClaw domain created. Official mode can use its configured model service; the custom gateway requires additional explicit credentials/configuration.

CE's local auth adapter grants local-owner access without browser authentication. Do **not** expose its editor/API publicly without an authenticated proxy. A connection-ready label verifies API reachability/auth/contract; it does not claim model quota or successful generation.

Remaining production prerequisite: configure an authorized model/voice provider and secure editor access. No model keys were invented, no paid story generated, and no social content published during development. Observe DramaClaw's upstream license and attribution requirements.

## Focused validation

`python -m pytest -q tests/test_dramaclaw_client.py tests/test_media_dramaclaw.py tests/test_holdings_v33.py::test_media_queue_requires_explicit_direct_production tests/test_holdings_v33.py::test_holdings_lifecycle_and_ledger`

`node tests/media-dramaclaw-ui.cjs` (Playwright + Chromium/Edge via `ZAR_TEST_BROWSER`). All external API/publication traffic is mocked. Python/JS syntax, VERSION consistency, startup and unchanged Stonks code are checked separately. These tests do not demonstrate a paid production generation, account quotas or real publication.
