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

Signed frame URLs expire after `ECHRYN_FRAME_URL_TTL_SECONDS` (24 hours by default). The prototype uses the configured Echryn API key as the signing secret. Production object storage can replace this local frame store without changing the extraction evidence contract.


## Native resource inspection

Before downloading the full video in `auto` mode, Echryn now inspects Instagram-native text-bearing resources:

- subtitle/caption/transcript-like fields in the media-info object
- exposed text-track URLs
- DASH/manifests for text-track signals
- native WebVTT/TTML text tracks when URLs are available

If substantive native text is found, Echryn can satisfy semantic coverage without downloading and processing the full media file. If native text resources are absent, non-substantive, or fail to load, Echryn falls back to the existing media evidence pipeline.

## Shared frame storage (Cloud Run)
Set ECHRYN_FRAME_BUCKET to a private Google Cloud Storage bucket to persist carousel slides and Reel frames across Cloud Run instances and revisions. Grant the Cloud Run service account storage.objectAdmin on that bucket. Keep public access prevention enabled and a one-day lifecycle delete policy, with soft-delete disabled, when one-day retention is desired. Signed /v1/frames URLs continue to use ECHRYN_API_KEY and expire after ECHRYN_FRAME_URL_TTL_SECONDS.

The URL-only MCP tool extract_visual_urls avoids embedding image bytes and instructs clients with image-capable browsing to inspect each required visual URL. Browser access is client-dependent; extract_reel continues to return native image content as the reliable fallback. Do not assume URLs are visually available without inspecting them.

## Auto-mode policy (2026-11-14)
- Auto is metadata-first for video Reels. A substantive caption or native text track can satisfy analysis without downloading the video. If a user requests visual specifics, invoke mode=evidence.
- Photo and carousel posts supply actual image evidence in Auto; all carousel slides are preserved in order. Mode=evidence/deep bypasses the caption-only shortcut.
- extract_visual_urls returns signed HTTPS links and no image blocks. ChatGPT's browsing tool may refuse access to the service even if HTTPS fetch works; never assert that pixels were inspected in that case. Use native MCP image delivery as fallback.

## Security & reliability audit (2026-11-14)
- External video, carousel and text-track URLs are restricted to trusted Instagram/Meta HTTPS hosts; untrusted hosts and redirects are refused. Text-track downloads are bounded.
- Signed frame URLs still expire in 24 hours, private Google Cloud storage retains temporary evidence until its one-day lifecycle cleanup, and REST extraction requires API key.
- Dependencies were updated (Pillow 13, Starlette 1.10, FastAPI 0.162.6, etc.) and local pip-audit reported no known vulnerabilities.
- **V1 limited-beta safeguard:** The MCP endpoint has a global, GCS-backed 10/hour and 50/UTC-day admission limit with one active extraction and an emergency disable switch. V1 remains unauthenticated and is not suitable for unrestricted public scaling; per-user OAuth and quotas remain V2 work.
- Local Cloud Run metadata cache is instance-specific. Image bytes now reside in shared storage, so HTTPS frames are not lost between instances, but cached metadata can be repeated.

## V1 limited public beta (November 2026)

**Read [PUBLIC_BETA.md](PUBLIC_BETA.md) before publishing or connecting.** The hosted MCP at https://echryn.fenilbuilds.com/mcp/ uses an operator-managed Instagram session for public posts. Users must never send login credentials. V1 is intentionally capped globally at 10 admissions per rolling hour, 50 per UTC calendar day, and one extraction in progress. On GCS outage it fails closed. Set ECHRYN_V1_LIMITS_ENABLED=true on Cloud Run; ECHRYN_PUBLIC_ENABLED=false is the emergency stop. Published open-source code is licensed Apache-2.0; preserve NOTICE attribution when redistributing.
