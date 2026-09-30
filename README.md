# Echryn — Reels API

**Echryn**  
**The API for short-form content.**

Echryn turns a short-form content URL into structured information. Instagram Reels are the first supported source.

## What v0.1 does

- Resolves Instagram Reel/post URLs to shortcode + numeric media ID.
- Uses authenticated Instagram media-info as the cheap first layer.
- Extracts creator, caption, engagement, media metadata, music/audio metadata and native text-bearing fields.
- Runs a semantic coverage gate so metadata is not confused with the actual message of the post.
- Supports three modes:
  - `metadata`: never download media.
  - `auto`: deep-inspect only when native data is not semantically sufficient.
  - `deep`: always inspect the actual media.
- Deep path temporarily downloads the video, probes it with FFprobe, samples frames with FFmpeg, sends frames to an optional hosted vision adapter, and sends media to an optional hosted speech adapter.
- Deletes temporary media automatically when the extraction workspace closes.
- Caches structured results by Instagram media ID + mode.
- Exposes REST and MCP over the same core.

## Security model

Use a dedicated company-owned Instagram account. Session cookies are password-equivalent secrets. Keep them in secret storage, never commit them, and never log them.

Echryn does not attempt CAPTCHA bypass, challenge bypass, rate-limit evasion, or stealth/fingerprint circumvention. If Instagram returns an authentication challenge, the extraction fails with `NEEDS_MANUAL_AUTH` and an operator must refresh the account session normally.

## Local run

```bash
cp .env.example .env
# fill INSTAGRAM_SESSIONID and optionally csrftoken/ds_user_id
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

Health:

```bash
curl http://localhost:8080/healthz
```

Synchronous extraction:

```bash
curl -X POST http://localhost:8080/v1/extractions/sync \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: change-me' \
  -d '{"url":"https://www.instagram.com/reel/Dd10cOlujGD/","mode":"auto"}'
```

If `ECHRYN_API_KEY=change-me`, auth is intentionally relaxed for local development. Set a real secret before deployment.

## MCP

Run the stdio MCP server:

```bash
python -m app.mcp_server
```

Tools:

- `extract_url(url, mode="auto", force_refresh=false)`
- `service_info()`

## Hosted vision adapter contract

Set `VISION_API_URL` to a small wrapper endpoint under your control. Echryn POSTs:

```json
{
  "model": "optional-model-name",
  "task": "Extract on-screen creator text, UI/background text, scene meaning, actions, products/sites, and uncertainties. Return concise JSON.",
  "images": ["data:image/jpeg;base64,..."]
}
```

Return any JSON object; Echryn stores it under `visual.value` with provenance.

## Hosted speech adapter contract

Set `SPEECH_API_URL` to a wrapper that accepts multipart form-data with `file` and optional `model`. Return JSON containing a `text` field. Empty text is normalized to `no_speech_detected`.

## Cloud Run

```bash
gcloud run deploy echryn \
  --source . \
  --region us-east1 \
  --allow-unauthenticated \
  --set-env-vars ECHRYN_API_KEY='YOUR_API_KEY'
```

Add Instagram and provider secrets through your cloud secret manager rather than command-line history.

## Production notes

The included cache is intentionally filesystem-backed for a single-instance prototype. Cloud Run filesystems are ephemeral, so before multi-instance production use, replace `FileCache` with D1/Redis/Postgres/object-backed cache. The extraction core is isolated so this swap does not change the API contract.
