# Echryn — Reels API

**Echryn**  
**The API for short-form content.**

Echryn turns a short-form content URL into structured information. Instagram Reels are the first supported source.

## What v0.1 does

- Resolves Instagram Reel/post URLs to shortcode + numeric media ID.
- Uses authenticated Instagram media-info as the cheap first layer.
- Extracts creator, caption, engagement, media metadata, music/audio metadata and native text-bearing fields.
- Runs a semantic coverage gate so metadata is not confused with the actual message of the post.
- Supports four modes:
  - `metadata`: never download media.
  - `auto`: deep-inspect only when native data is not semantically sufficient.
  - `evidence`: return representative frame evidence plus audio evidence.\n  - `deep`: always inspect the actual media.
- Deep/evidence paths temporarily download the video, probe it with FFprobe, and sample frames with FFmpeg. Multimodal callers receive compressed WebP frames directly and skip OCR. Non-multimodal callers can use local Tesseract OCR. Audio uses native licensed-music policy, local Silero VAD, and local faster-whisper only when useful speech is present.
- Deletes temporary media automatically when the extraction workspace closes.
- Caches structured results by Instagram media ID + mode + multimodal capability.
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

## Local visual policy\n\nSet `multimodal=true` for multimodal callers. Echryn then skips OCR and returns representative compressed frames directly. Non-multimodal callers use local OCR as a fallback text representation.\n\n## Local audio pipeline

Audio processing is local:\n\n\`\`\`text\nnative audio metadata\n→ licensed music with no original-sound signal: skip transcription\n→ otherwise Silero VAD\n→ no useful speech: no_speech_detected\n→ speech: faster-whisper\n→ transcript + language + segment/word timestamps + provenance\n\`\`\`\n\nThe default transcription model is \`base\` on CPU with \`int8\` compute. The model is loaded lazily only when transcription is actually required.\n\n## Cloud Run

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
