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
  - `evidence`: return representative frame evidence plus audio evidence.
  - `deep`: always inspect the actual media.
- Deep/evidence paths temporarily download the video, probe it with FFprobe, and sample frames with FFmpeg. Multimodal callers receive compressed WebP frame evidence and skip OCR. Non-multimodal callers can use local Tesseract OCR. Audio treats native music metadata as context only, runs local Silero VAD whenever an audio stream exists, and runs local faster-whisper only when useful speech is present.
- Deletes temporary media automatically when the extraction workspace closes.
- Caches request variants under one stable Instagram media identity. Cached signed frame URLs are refreshed on reuse.
- Exposes REST and MCP over the same core.

## Security model

Use a dedicated company-owned Instagram account. Session cookies are password-equivalent secrets. Keep them in secret storage, never commit them, and never log them.

Echryn does not attempt CAPTCHA bypass, challenge bypass, rate-limit evasion, or stealth/fingerprint circumvention. If Instagram returns an authentication challenge, the extraction fails with `NEEDS_MANUAL_AUTH` and an operator must refresh the account session normally.

## Local run

```bash
cp .env.example .env
# fill INSTAGRAM_SESSIONID and optionally csrftoken/ds_user_id
pip install -r requirements.txt
python -m uvicorn app.main:app --port 8080
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

- `extract_url(url, mode="auto", multimodal=false, force_refresh=false)`
- `service_info()`

## Local visual policy

Set `multimodal=true` for multimodal callers. Echryn then skips OCR and returns representative compressed frames directly. Non-multimodal callers use local OCR as a fallback text representation.

## Local audio pipeline

Audio processing is local:

```text
native audio metadata (context only)
→ Silero VAD for every available audio stream
→ no useful speech: no_speech_detected
→ speech: faster-whisper
→ transcript + language + segment/word timestamps + provenance
```

The default transcription model is `base` on CPU with `int8` compute. The model is loaded lazily only when transcription is actually required.

## Cloud Run

```bash
gcloud run deploy echryn \
  --source . \
  --region us-east1 \
  --allow-unauthenticated \
  --set-env-vars ECHRYN_API_KEY='YOUR_API_KEY'
```

Add Instagram session secrets through your cloud secret manager rather than command-line history.

## Production notes

The included cache is filesystem-backed for a single-instance V1. Each Instagram media ID owns one cache document containing independently expiring request variants. Stored frame evidence is pruned with the cache TTL, and signed frame URLs are regenerated when cached results are reused. Cloud Run filesystems are ephemeral, so multi-instance production should replace the filesystem cache/frame store with Redis/Postgres plus object storage without changing the API contract.


## Audio dependency compatibility

Echryn pins `av<19` because faster-whisper 1.2.1 still calls
`av.open(..., metadata_errors="ignore")`, while PyAV 19 removed that argument.


## Frame delivery

Representative frames support three delivery modes:

- `urls` (default): persist compressed WebP evidence under the Echryn data directory and return signed temporary URLs.
- `inline`: return base64 WebP data URLs for callers that explicitly need inline evidence.
- `none`: suppress frame payload delivery.

Request example:

```json
{
  "url": "https://www.instagram.com/reel/...",
  "mode": "evidence",
  "multimodal": true,
  "frame_delivery": "urls"
}
```

Signed frame URLs expire after `ECHRYN_FRAME_URL_TTL_SECONDS` (7 days by default). The prototype uses the configured Echryn API key as the signing secret. Production object storage can replace this local frame store without changing the extraction evidence contract.


## Native resource inspection

Before downloading the full video in `auto` mode, Echryn now inspects Instagram-native text-bearing resources:

- subtitle/caption/transcript-like fields in the media-info object
- exposed text-track URLs
- DASH/manifests for text-track signals
- native WebVTT/TTML text tracks when URLs are available

If substantive native text is found, Echryn can satisfy semantic coverage without downloading and processing the full media file. If native text resources are absent, non-substantive, or fail to load, Echryn falls back to the existing media evidence pipeline.
