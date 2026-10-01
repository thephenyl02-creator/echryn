# Echryn Architecture — Frozen V1 Source of Truth

Status: FROZEN unless explicitly changed by Fenil.

## Product boundary
Echryn is primarily **content resolution + extraction + evidence delivery**.

It is not a mandatory paid multimodal-model wrapper. Core operation must work without OpenAI, Gemini, Claude, or any other paid vision/speech API.

## Core pipeline
```text
INPUT
URL / media identifier
  ↓
1. PLATFORM RESOLVER
   Instagram URL → shortcode → media ID
   Later: TikTok / Shorts / etc.
  ↓
2. NATIVE CONTENT LAYER
   Platform-native structured data:
   author, caption, music/audio, engagement, duration,
   accessibility, overlays/native text, subtitles/transcripts,
   media resources, DASH/manifests, other exposed content fields
  ↓
3. SEMANTIC COVERAGE GATE
   Does native data actually explain the content?
   yes → RETURN
   no  → inspect native resources/manifests/text tracks
  ↓
   enough? → RETURN
   not enough → TEMPORARY MEDIA DOWNLOAD
  ↓
4. MEDIA EVIDENCE LAYER
   FFprobe + FFmpeg:
   scene-change detection, true timestamps, representative frames,
   temporal fallback anchors, perceptual dedupe, frame sequence
  ↓
5. VISUAL EVIDENCE POLICY
   If caller is multimodal:
   - return representative compressed frames directly
   - skip OCR entirely
   - caller interprets the frames itself

   If caller is not multimodal:
   - run local OCR as a fallback text representation
   - Tesseract initially
   - stronger local/open OCR later if needed

   Later optional local CV:
   - embeddings
   - object detection
   - UI/layout detection
   - temporal frame comparison
   No mandatory paid VLM/API.
  ↓
6. AUDIO EVIDENCE LAYER
   Apply native audio metadata as a hint, not as proof of no speech.
   - licensed music may still contain voice-over
   - if an audio stream exists, run local Silero VAD
   - no useful speech → no_speech_detected
   - useful speech → local faster-whisper
   - return transcript, language, segment timestamps, word timestamps,
     detector statistics, model metadata and provenance
   No mandatory paid speech API.
  ↓
7. EVIDENCE ASSEMBLY
   Merge native + frames + speech + optional OCR + media metadata.
   Preserve source + confidence/status.
  ↓
CACHE RESULT
  ↓
DELETE TEMP MEDIA / FRAMES
```

## Request modes
- `metadata`: Native/platform information only. No media download.
- `auto`: Cheap-first. Download media only when semantic coverage is insufficient.
- `evidence`: Return native data + representative compressed frames + audio evidence; OCR is conditional on caller capability.
- `deep`: Force actual media inspection even when native metadata appears sufficient.

Caller capability hint:
```json
{"multimodal": true}
```

When `multimodal=true`, Echryn skips OCR and returns representative frame evidence directly. OCR is reserved for non-multimodal callers.

`deep` does not mean “call a paid AI model.”

## Visual evidence delivery
Echryn should expose actual representative visual evidence to multimodal clients.

Preferred default:
- representative frames only
- perceptual dedupe
- resize where appropriate
- WebP/JPEG compression
- signed/temporary URLs or stored object references

Optional:
- inline base64 only when requested

Potential API controls:
```text
frames=none|urls|inline
frame_format=webp|jpeg|png
quality=...
max_frames=...
```

A multimodal caller can inspect the returned frames itself. Echryn does not need its own paid multimodal model for that use case.

Current frame delivery implementation:
- `urls` is the default and persists compressed WebP evidence in the local Echryn data directory.
- returned URLs are temporary HMAC-signed frame endpoints.
- `inline` remains available explicitly for base64 data URLs.
- `none` suppresses frame delivery.
- production object storage can later replace the local store without changing the evidence contract.

## Interpretation vs evidence
Echryn V1 focuses on **evidence**:
- what native data says
- representative visual frames
- what speech exists
- OCR only when a non-multimodal caller needs text representation
- where each piece came from

Interpretation is optional and can later use deterministic/local logic, local classifiers/encoders, an optional locally hosted VLM, or optional external adapters only if explicitly chosen.

## Web scraping boundary
Keep traditional webpage scraping architecturally separate.

### Echryn Core
```text
content URL
→ underlying media/content object
→ native platform data
→ actual media evidence
```

### Possible future Echryn Web
```text
web page
→ HTML / DOM / webpage parsing
```

Page parsing may assist URL resolution, but conventional webpage scraping is not the core architecture.

## Provenance and statuses
Every extracted datum should preserve its origin.

Example:
```json
{
  "text": "Reinvent them with the help of AI",
  "source": "frame_06_ocr",
  "timestamp": 8.4,
  "status": "available"
}
```

Statuses:
```text
available
absent
not_exposed
not_applicable
skipped_by_policy
failed
no_speech_detected
```

Rules:
- weak OCR never overwrites stronger native evidence
- evidence sources remain distinguishable
- failures remain explicit

## Caching
Cache by stable platform content identity, e.g.:
```text
instagram:3996330882590454147
```

Once evidence exists, repeated requests should reuse cached extraction rather than repeat platform calls, media download, FFmpeg, OCR, or transcription.

## No mandatory paid APIs
The following are **not required** for Echryn Core:
```text
VISION_API_*
SPEECH_API_*
OpenAI API
Gemini API
Claude API
```

External providers may exist later as optional adapters, but Echryn must function without them.

## Current proven V0.1 state
Working:
```text
Instagram Reel URL
→ shortcode
→ media ID
→ authenticated native media-info
→ semantic coverage gate
→ temporary media download when needed
→ FFprobe / FFmpeg
→ sampled frames
→ temporary media cleanup
```

Known target:
```text
https://www.instagram.com/reel/Dd10cOlujGD/
shortcode: Dd10cOlujGD
media ID: 3996330882590454147
```

Current visual implementation:
```text
scene detection + temporal fallback anchors
→ true timestamped sampled frames
→ perceptual duplicate removal / novelty selection
→ local OCR only for non-multimodal callers
→ compressed WebP frame evidence
→ merge into result
```

Audio implementation:
```text
native audio metadata (context only)
→ Silero VAD at 16 kHz
→ no useful speech: stop
→ useful speech: faster-whisper (lazy-loaded local model)
→ transcript + segment/word timestamps + provenance
```

Default local transcription configuration:
```text
model=base
device=cpu
compute_type=int8
beam_size=1
```

The Whisper model is loaded lazily only when speech reaches the transcription stage.

## Architecture-change rule
Do not change this architecture implicitly.

Any material change—especially adding mandatory paid APIs, replacing local evidence extraction, or turning Echryn Core into a conventional scraper—requires explicit approval first.
