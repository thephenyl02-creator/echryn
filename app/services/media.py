import asyncio
import base64
import hashlib
import hmac
import time
import json
import re
import shutil
import subprocess
import tempfile
from difflib import SequenceMatcher
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from app.config import settings


async def _run(*args: str) -> tuple[int, str, str]:
    def _sync_run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(args),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
        )

    completed = await asyncio.to_thread(_sync_run)
    return completed.returncode, completed.stdout, completed.stderr


async def download_media(url: str, dest: Path) -> dict[str, Any]:
    limit = settings.echryn_max_media_mb * 1024 * 1024
    total = 0
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        async with client.stream("GET", url, headers={"User-Agent": settings.instagram_user_agent}) as r:
            r.raise_for_status()
            with dest.open("wb") as f:
                async for chunk in r.aiter_bytes():
                    total += len(chunk)
                    if total > limit:
                        raise RuntimeError("Media exceeded configured size limit")
                    f.write(chunk)
    return {"bytes": total, "path": str(dest)}


async def probe_media(path: Path) -> dict[str, Any]:
    code, out, err = await _run(
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=index,codec_type,codec_name,width,height",
        "-of", "json", str(path),
    )
    if code != 0:
        raise RuntimeError(f"ffprobe failed: {err[-500:]}")
    return json.loads(out)


async def _duration_seconds(path: Path) -> float:
    code, out, err = await _run(
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    )
    if code != 0:
        raise RuntimeError(f"ffprobe duration failed: {err[-500:]}")
    try:
        return max(0.0, float(out.strip()))
    except ValueError as exc:
        raise RuntimeError("ffprobe returned invalid media duration") from exc


async def _scene_timestamps(path: Path) -> list[float]:
    threshold = settings.echryn_scene_threshold
    code, _, err = await _run(
        "ffmpeg", "-hide_banner", "-loglevel", "info", "-i", str(path),
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-an", "-f", "null", "-",
    )
    if code != 0:
        raise RuntimeError(f"ffmpeg scene detection failed: {err[-500:]}")

    timestamps: list[float] = []
    for match in re.finditer(r"pts_time:([0-9.]+)", err):
        try:
            timestamps.append(float(match.group(1)))
        except ValueError:
            continue
    return timestamps


def _build_frame_timestamps(
    duration_seconds: float,
    scene_timestamps: list[float],
    limit: int,
    min_gap_seconds: float,
) -> list[float]:
    if duration_seconds <= 0 or limit <= 0:
        return []

    # Keep a safety margin from EOF. Seeking to the exact final timestamp can
    # produce no decodable packet on short/re-encoded social videos.
    end = max(0.0, duration_seconds - 0.35)

    # Scene cuts have priority over fallback anchors. Start/end are also treated
    # as first-class evidence points so temporal coverage is always preserved.
    scene_candidates = [0.0]
    scene_candidates.extend(ts for ts in scene_timestamps if 0.0 < ts < end)
    if end > 0:
        scene_candidates.append(end)
    scene_candidates.sort()

    distinct_scenes: list[float] = []
    for ts in scene_candidates:
        if not distinct_scenes or ts - distinct_scenes[-1] >= min_gap_seconds:
            distinct_scenes.append(ts)

    # If there are more scene points than the response budget permits, thin
    # only the scene points themselves. Never let fallback anchors displace a
    # valid scene cut.
    if len(distinct_scenes) > limit:
        indices = _selected_frame_indices(len(distinct_scenes), limit)
        return [round(distinct_scenes[index], 3) for index in indices]

    selected = list(distinct_scenes)

    # Hard cuts can miss text swaps, fades, and other meaningful changes, so
    # fill remaining capacity with temporal anchors that are sufficiently far
    # from already-selected scene points.
    if len(selected) < limit:
        if limit == 1:
            anchors = [0.0]
        else:
            anchors = [end * i / (limit - 1) for i in range(limit)]

        for ts in anchors:
            if len(selected) >= limit:
                break
            if all(abs(ts - existing) >= min_gap_seconds for existing in selected):
                selected.append(ts)

    selected.sort()
    return [round(ts, 3) for ts in selected]


def _frame_timestamp_seconds(path: Path, fallback_index: int) -> float:
    match = re.search(r"-t([0-9]+(?:\.[0-9]+)?)$", path.stem)
    if match:
        try:
            return round(float(match.group(1)), 3)
        except ValueError:
            pass
    return round(fallback_index * 1.5, 3)


async def extract_frames(path: Path, out_dir: Path, max_frames: int | None = None) -> list[Path]:
    max_frames = max_frames or settings.echryn_max_frames
    out_dir.mkdir(parents=True, exist_ok=True)

    duration = await _duration_seconds(path)
    scenes = await _scene_timestamps(path)
    timestamps = _build_frame_timestamps(
        duration,
        scenes,
        max_frames,
        settings.echryn_scene_min_gap_seconds,
    )

    frames: list[Path] = []
    for index, timestamp in enumerate(timestamps):
        attempts = [timestamp]
        if duration > 0:
            attempts.extend(
                max(0.0, timestamp - backoff)
                for backoff in (0.15, 0.35, 0.75)
            )

        extracted = False
        last_error = ""
        used_timestamp = timestamp

        for attempt in attempts:
            dest = out_dir / f"frame-{index:03d}-t{attempt:.3f}.jpg"
            code, _, err = await _run(
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-ss", f"{attempt:.3f}", "-i", str(path),
                "-frames:v", "1",
                "-vf", "scale='min(960,iw)':-2",
                "-q:v", "3", str(dest),
            )
            last_error = err
            if code == 0 and dest.exists() and dest.stat().st_size > 0:
                frames.append(dest)
                used_timestamp = attempt
                extracted = True
                break
            if dest.exists():
                dest.unlink(missing_ok=True)

        if not extracted:
            # A single unusable timestamp should not fail the whole extraction.
            # Continue with the other representative frames and only fail if
            # nothing at all could be extracted.
            continue

    if not frames:
        raise RuntimeError(f"ffmpeg could not extract any representative frames: {last_error[-500:]}")

    return frames


def _clean_ocr_text(text: str) -> str:
    lines = []
    for raw_line in text.replace("\r", "\n").split("\n"):
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        if sum(ch.isalnum() for ch in line) < 2:
            continue
        lines.append(line)
    return "\n".join(lines)


def _ocr_score(text: str) -> int:
    if not text:
        return 0
    return sum(ch.isalnum() for ch in text) + (4 * len(text.splitlines()))


def _make_ocr_variants(path: Path) -> list[tuple[str, Path]]:
    variants: list[tuple[str, Path]] = [("original", path)]
    base_dir = path.parent / "_ocr"
    base_dir.mkdir(parents=True, exist_ok=True)

    with Image.open(path) as source:
        rgb = source.convert("RGB")
        width, height = rgb.size

        # Crop away the outer UI rails while retaining creator text and the main scene.
        crop = rgb.crop(
            (
                int(width * 0.04),
                int(height * 0.04),
                int(width * 0.96),
                int(height * 0.92),
            )
        )
        scale = 2
        crop = crop.resize(
            (crop.width * scale, crop.height * scale),
            Image.Resampling.LANCZOS,
        )

        gray = ImageOps.grayscale(crop)
        gray = ImageOps.autocontrast(gray, cutoff=1)
        gray = ImageEnhance.Contrast(gray).enhance(1.65)
        gray = gray.filter(ImageFilter.SHARPEN)

        enhanced = base_dir / f"{path.stem}-enhanced.png"
        gray.save(enhanced, format="PNG")
        variants.append(("enhanced", enhanced))

        # Two binary variants handle bright overlay text against changing backgrounds.
        for threshold in (150, 190):
            binary = gray.point(lambda p, t=threshold: 255 if p >= t else 0, mode="1")
            binary_path = base_dir / f"{path.stem}-binary-{threshold}.png"
            binary.save(binary_path, format="PNG")
            variants.append((f"binary-{threshold}", binary_path))

            inverted = ImageOps.invert(binary.convert("L"))
            inverted_path = base_dir / f"{path.stem}-binary-{threshold}-inv.png"
            inverted.save(inverted_path, format="PNG")
            variants.append((f"binary-{threshold}-inv", inverted_path))

    return variants


def _candidate_line_score(line: str) -> float:
    clean = re.sub(r"\s+", " ", line).strip()
    if not clean:
        return -1.0
    alnum = sum(ch.isalnum() for ch in clean)
    words = re.findall(r"[A-Za-z0-9]+", clean)
    alpha_words = [w for w in words if any(ch.isalpha() for ch in w)]
    noise = sum(1 for ch in clean if not (ch.isalnum() or ch.isspace() or ch in "'&-"))
    return (
        alnum
        + (7 * len(alpha_words))
        + (4 if len(alpha_words) >= 3 else 0)
        - (3 * noise)
    )


def _merge_variant_lines(texts: list[str]) -> str:
    chosen: list[str] = []
    for text in texts:
        for raw in text.splitlines():
            line = re.sub(r"\s+", " ", raw).strip(" |_=~")
            if sum(ch.isalnum() for ch in line) < 4:
                continue

            matched = None
            for i, existing in enumerate(chosen):
                if _is_near_duplicate(line, existing, threshold=0.64):
                    matched = i
                    break

            if matched is None:
                chosen.append(line)
            elif _candidate_line_score(line) > _candidate_line_score(chosen[matched]):
                chosen[matched] = line

    return "\n".join(chosen)


async def _ocr_frame(path: Path) -> tuple[str, str]:
    outputs: list[tuple[str, str, str]] = []

    for variant_name, variant_path in _make_ocr_variants(path):
        for psm in ("6", "11"):
            code, out, _ = await _run(
                "tesseract",
                str(variant_path),
                "stdout",
                "-l",
                "eng",
                "--oem",
                "1",
                "--psm",
                psm,
                "-c",
                "preserve_interword_spaces=1",
            )
            if code == 0:
                cleaned = _clean_ocr_text(out)
                if cleaned:
                    outputs.append((cleaned, variant_name, psm))

    if not outputs:
        return "", "unknown"

    merged = _merge_variant_lines([item[0] for item in outputs])
    if merged:
        best_meta = max(outputs, key=lambda item: _ocr_score(item[0]))
        return merged, f"ensemble:{best_meta[1]}:psm{best_meta[2]}"

    text, variant_name, psm = max(outputs, key=lambda item: _ocr_score(item[0]))
    return text, f"{variant_name}:psm{psm}"


async def _prominent_ocr_frame(path: Path) -> str:
    variants = _make_ocr_variants(path)
    preferred = next((p for name, p in variants if name == "enhanced"), path)
    code, out, _ = await _run(
        "tesseract", str(preferred), "stdout", "-l", "eng", "--oem", "1", "--psm", "11", "tsv"
    )
    if code != 0 or not out.strip():
        return ""

    with Image.open(preferred) as image:
        _, image_height = image.size

    rows = out.splitlines()
    if not rows:
        return ""

    header = rows[0].split("\t")
    index = {name: i for i, name in enumerate(header)}

    required = {
        "block_num",
        "par_num",
        "line_num",
        "word_num",
        "left",
        "conf",
        "height",
        "text",
    }
    if not required.issubset(index):
        return ""

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}

    for row in rows[1:]:
        cols = row.split("\t")
        if len(cols) < len(header):
            continue

        word = cols[index["text"]].strip()
        if not word:
            continue

        try:
            conf = float(cols[index["conf"]])
            height = int(cols[index["height"]])
            left = int(cols[index["left"]])
            word_num = int(cols[index["word_num"]])
        except ValueError:
            continue

        if conf < 35:
            continue

        key = (
            cols[index["block_num"]],
            cols[index["par_num"]],
            cols[index["line_num"]],
        )
        grouped.setdefault(key, []).append(
            {
                "word_num": word_num,
                "left": left,
                "height": height,
                "conf": conf,
                "text": word,
            }
        )

    candidates: list[dict[str, Any]] = []
    for words in grouped.values():
        ordered = sorted(words, key=lambda item: (item["left"], item["word_num"]))
        line = re.sub(r"\s+", " ", " ".join(item["text"] for item in ordered)).strip()
        if sum(ch.isalnum() for ch in line) < 3:
            continue

        heights = sorted(item["height"] for item in ordered)
        median_height = heights[len(heights) // 2]
        max_height = max(heights)
        avg_conf = sum(item["conf"] for item in ordered) / len(ordered)

        candidates.append(
            {
                "text": line,
                "median_height": median_height,
                "max_height": max_height,
                "avg_conf": avg_conf,
            }
        )

    if not candidates:
        return ""

    largest = max(item["max_height"] for item in candidates)
    min_prominent_height = max(
        24,
        int(image_height * 0.025),
        int(largest * 0.60),
    )

    lines: list[str] = []
    for item in candidates:
        if item["max_height"] < min_prominent_height:
            continue
        if item["avg_conf"] < 45:
            continue
        lines.append(item["text"])

    return "\n".join(lines)


def deduplicate_text_lines(texts: list[str], threshold: float = 0.88) -> list[str]:
    unique: list[str] = []
    for text in texts:
        for raw_line in text.splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip()
            if not line:
                continue
            if any(_is_near_duplicate(line, existing, threshold=threshold) for existing in unique):
                continue
            unique.append(line)
    return unique


def _normalized_for_compare(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _is_near_duplicate(a: str, b: str, threshold: float = 0.88) -> bool:
    na = _normalized_for_compare(a)
    nb = _normalized_for_compare(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    return SequenceMatcher(None, na, nb).ratio() >= threshold


def deduplicate_ocr_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    for entry in entries:
        text = entry.get("text") or ""
        if not text:
            continue
        if any(_is_near_duplicate(text, existing.get("text") or "") for existing in unique):
            continue
        unique.append(entry)
    return unique


def _selected_frame_indices(total: int, limit: int) -> list[int]:
    if total <= 0 or limit <= 0:
        return []
    if total <= limit:
        return list(range(total))
    if limit == 1:
        return [0]
    return sorted({round(i * (total - 1) / (limit - 1)) for i in range(limit)})


def _dhash64(path: Path) -> int:
    with Image.open(path) as image:
        gray = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
        pixels = list(gray.getdata())

    value = 0
    for row in range(8):
        offset = row * 9
        for col in range(8):
            value <<= 1
            value |= int(pixels[offset + col] > pixels[offset + col + 1])
    return value


def _hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def select_representative_frame_indices(
    frames: list[Path],
    limit: int,
    duplicate_distance: int = 6,
) -> list[int]:
    if not frames or limit <= 0:
        return []
    if len(frames) <= limit:
        return list(range(len(frames)))

    hashes = [_dhash64(frame) for frame in frames]

    # First remove frames that are perceptually almost identical to something
    # already retained. This is intentionally conservative: dHash distance 0
    # means identical structure; small distances are near-duplicates.
    unique_candidates: list[int] = []
    for index, frame_hash in enumerate(hashes):
        if any(
            _hamming_distance(frame_hash, hashes[kept]) <= duplicate_distance
            for kept in unique_candidates
        ):
            continue
        unique_candidates.append(index)

    if not unique_candidates:
        return _selected_frame_indices(len(frames), limit)

    if len(unique_candidates) <= limit:
        return unique_candidates

    # Preserve temporal coverage by seeding the first and last distinct frames,
    # then greedily add the candidate that is most visually novel relative to
    # what is already selected. Temporal distance breaks visual-score ties.
    selected = [unique_candidates[0]]
    if limit > 1 and unique_candidates[-1] != unique_candidates[0]:
        selected.append(unique_candidates[-1])

    while len(selected) < limit:
        remaining = [i for i in unique_candidates if i not in selected]
        if not remaining:
            break

        def score(index: int) -> tuple[int, int]:
            visual_novelty = min(
                _hamming_distance(hashes[index], hashes[chosen])
                for chosen in selected
            )
            temporal_novelty = min(abs(index - chosen) for chosen in selected)
            return visual_novelty, temporal_novelty

        selected.append(max(remaining, key=score))

    return sorted(selected)


def _frame_signature(extraction_id: str, filename: str, expires: int) -> str:
    secret = settings.echryn_api_key or "change-me"
    payload = f"{extraction_id}:{filename}:{expires}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def build_frame_url(extraction_id: str, filename: str, now: int | None = None) -> str:
    issued = int(time.time() if now is None else now)
    expires = issued + settings.echryn_frame_url_ttl_seconds
    signature = _frame_signature(extraction_id, filename, expires)
    return (
        f"{settings.echryn_public_base_url.rstrip('/')}"
        f"/v1/frames/{extraction_id}/{filename}"
        f"?exp={expires}&sig={signature}"
    )


def validate_frame_signature(
    extraction_id: str,
    filename: str,
    expires: int,
    signature: str,
    now: int | None = None,
) -> bool:
    current = int(time.time() if now is None else now)
    if expires < current:
        return False
    expected = _frame_signature(extraction_id, filename, expires)
    return hmac.compare_digest(expected, signature)


def refresh_frame_urls(result: dict[str, Any]) -> None:
    extraction_id = str(result.get("id") or "")
    if not extraction_id:
        return

    visual = result.get("visual", {})
    frames = visual.get("frames", [])
    images = visual.get("images", [])
    if not isinstance(frames, list) or not isinstance(images, list):
        return

    for frame in frames + images:
        if not isinstance(frame, dict) or frame.get("delivery") != "url":
            continue

        filename = frame.get("filename")
        if not filename:
            existing_url = frame.get("url")
            if isinstance(existing_url, str):
                filename = Path(urlparse(existing_url).path).name
        if not filename:
            index = frame.get("frame_index")
            if isinstance(index, int):
                filename = f"frame-{index:03d}.webp"
        if not filename:
            continue

        frame["filename"] = filename
        frame["url"] = build_frame_url(extraction_id, filename)


def touch_frame_evidence(extraction_id: str) -> None:
    if not extraction_id:
        return
    frame_dir = settings.data_dir / settings.echryn_frame_store_subdir / extraction_id
    if frame_dir.is_dir():
        now = time.time()
        frame_dir.touch(exist_ok=True)
        try:
            import os
            os.utime(frame_dir, (now, now))
        except OSError:
            pass


def cleanup_stale_frame_evidence(max_age_seconds: int, now: float | None = None) -> int:
    root = settings.data_dir / settings.echryn_frame_store_subdir
    if not root.exists():
        return 0

    current = time.time() if now is None else now
    removed = 0

    for child in root.iterdir():
        if not child.is_dir():
            continue
        try:
            age = current - child.stat().st_mtime
        except OSError:
            continue
        if age <= max_age_seconds:
            continue
        try:
            shutil.rmtree(child)
            removed += 1
        except OSError:
            continue

    return removed


def _webp_bytes(path: Path) -> tuple[bytes, int, int]:
    with Image.open(path) as image:
        image = image.convert("RGB")
        width, height = image.size
        max_width = getattr(settings, "echryn_frame_max_width", 640)
        if width > max_width:
            new_height = round(height * (max_width / width))
            image = image.resize((max_width, new_height), Image.Resampling.LANCZOS)
            width, height = image.size

        buffer = BytesIO()
        image.save(
            buffer,
            format="WEBP",
            quality=getattr(settings, "echryn_frame_webp_quality", 70),
            method=6,
        )

    return buffer.getvalue(), width, height


def _webp_data_url(path: Path) -> tuple[str, int, int, int]:
    raw, width, height = _webp_bytes(path)
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:image/webp;base64,{encoded}", len(raw), width, height


def _store_webp_frame(
    path: Path,
    extraction_id: str,
    frame_index: int,
) -> tuple[Path, int, int, int]:
    raw, width, height = _webp_bytes(path)
    frame_dir = settings.data_dir / settings.echryn_frame_store_subdir / extraction_id
    frame_dir.mkdir(parents=True, exist_ok=True)
    dest = frame_dir / f"frame-{frame_index:03d}.webp"
    dest.write_bytes(raw)
    from app.storage.frame_store import upload_frame
    upload_frame(dest, extraction_id, dest.name, "image/webp")
    return dest, len(raw), width, height


async def local_visual_analyze(
    frames: list[Path],
    frame_delivery: str = "urls",
    extraction_id: str | None = None,
    run_ocr: bool = True,
) -> dict[str, Any]:
    ocr_entries: list[dict[str, Any]] = []
    prominent_per_frame: list[str] = []

    if run_ocr:
        for index, frame in enumerate(frames):
            text, psm = await _ocr_frame(frame)
            prominent_text = await _prominent_ocr_frame(frame)
            prominent_per_frame.append(prominent_text)
            ocr_entries.append(
                {
                    "frame_index": index,
                    "timestamp_seconds": _frame_timestamp_seconds(frame, index),
                    "text": text,
                    "prominent_text": prominent_text,
                    "engine": "tesseract",
                    "psm": psm,
                }
            )

    unique_entries = deduplicate_ocr_entries(ocr_entries) if run_ocr else []
    combined_text = "\n".join(entry["text"] for entry in unique_entries if entry.get("text")).strip()
    prominent_lines = deduplicate_text_lines(prominent_per_frame) if run_ocr else []
    prominent_text = "\n".join(prominent_lines).strip()

    visual_frames: list[dict[str, Any]] = []
    if frame_delivery != "none":
        selected_indices = select_representative_frame_indices(
            frames,
            getattr(settings, "echryn_evidence_max_frames", 6),
        )
        for index in selected_indices:
            frame_payload: dict[str, Any] = {
                "frame_index": index,
                "timestamp_seconds": _frame_timestamp_seconds(frames[index], index),
                "mime_type": "image/webp",
                "selection": "perceptual_novelty",
            }

            if frame_delivery == "inline":
                data_url, compressed_bytes, width, height = _webp_data_url(frames[index])
                frame_payload.update(
                    {
                        "width": width,
                        "height": height,
                        "compressed_bytes": compressed_bytes,
                        "data_url": data_url,
                        "delivery": "inline",
                    }
                )
            elif frame_delivery == "urls":
                if not extraction_id:
                    raise RuntimeError("extraction_id is required for URL frame delivery")
                stored, compressed_bytes, width, height = await asyncio.to_thread(_store_webp_frame,
                    frames[index],
                    extraction_id,
                    index,
                )
                frame_payload.update(
                    {
                        "width": width,
                        "height": height,
                        "compressed_bytes": compressed_bytes,
                        "filename": stored.name,
                        "url": build_frame_url(extraction_id, stored.name),
                        "delivery": "url",
                    }
                )
            else:
                raise ValueError(f"Unsupported frame delivery mode: {frame_delivery}")

            visual_frames.append(frame_payload)

    has_visual_evidence = bool(combined_text or visual_frames)
    return {
        "status": "available" if has_visual_evidence else "absent",
        "source": "local_visual",
        "ocr": (
            {
                "status": "available" if combined_text else "absent",
                "engine": "tesseract",
                "text": combined_text,
                "prominent_text": prominent_text,
                "frames": ocr_entries,
                "unique_frames": unique_entries,
            }
            if run_ocr
            else {
                "status": "skipped_by_policy",
                "reason": "multimodal caller receives visual frame evidence directly",
            }
        ),
        "frames": visual_frames,
    }


def temp_workspace(prefix: str):
    return tempfile.TemporaryDirectory(prefix=prefix)
