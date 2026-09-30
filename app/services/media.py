import asyncio
import base64
import json
import re
import subprocess
import tempfile
from difflib import SequenceMatcher
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

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


async def extract_frames(path: Path, out_dir: Path, max_frames: int | None = None) -> list[Path]:
    max_frames = max_frames or settings.echryn_max_frames
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "frame-%03d.jpg")
    code, _, err = await _run(
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
        "-vf", "fps=1/1.5,scale='min(960,iw)':-2", "-frames:v", str(max_frames),
        "-q:v", "3", pattern,
    )
    if code != 0:
        raise RuntimeError(f"ffmpeg frame extraction failed: {err[-500:]}")
    return sorted(out_dir.glob("frame-*.jpg"))


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


async def _ocr_frame(path: Path) -> tuple[str, str]:
    candidates: list[tuple[str, str]] = []
    for psm in ("6", "11"):
        code, out, _ = await _run("tesseract", str(path), "stdout", "--psm", psm)
        if code == 0:
            cleaned = _clean_ocr_text(out)
            candidates.append((cleaned, psm))

    if not candidates:
        return "", "unknown"

    text, psm = max(candidates, key=lambda item: _ocr_score(item[0]))
    return text, psm


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


def _webp_data_url(path: Path) -> tuple[str, int, int, int]:
    with Image.open(path) as image:
        image = image.convert("RGB")
        width, height = image.size
        max_width = settings.echryn_frame_max_width
        if width > max_width:
            new_height = round(height * (max_width / width))
            image = image.resize((max_width, new_height), Image.Resampling.LANCZOS)
            width, height = image.size

        buffer = BytesIO()
        image.save(
            buffer,
            format="WEBP",
            quality=settings.echryn_frame_webp_quality,
            method=6,
        )

    raw = buffer.getvalue()
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:image/webp;base64,{encoded}", len(raw), width, height


async def local_visual_analyze(
    frames: list[Path],
    include_inline_frames: bool = False,
) -> dict[str, Any]:
    ocr_entries: list[dict[str, Any]] = []

    for index, frame in enumerate(frames):
        text, psm = await _ocr_frame(frame)
        ocr_entries.append(
            {
                "frame_index": index,
                "timestamp_seconds": round(index * 1.5, 3),
                "text": text,
                "engine": "tesseract",
                "psm": psm,
            }
        )

    unique_entries = deduplicate_ocr_entries(ocr_entries)
    combined_text = "\n".join(entry["text"] for entry in unique_entries if entry.get("text")).strip()

    visual_frames: list[dict[str, Any]] = []
    if include_inline_frames:
        for index in _selected_frame_indices(len(frames), settings.echryn_evidence_max_frames):
            data_url, compressed_bytes, width, height = _webp_data_url(frames[index])
            visual_frames.append(
                {
                    "frame_index": index,
                    "timestamp_seconds": round(index * 1.5, 3),
                    "mime_type": "image/webp",
                    "width": width,
                    "height": height,
                    "compressed_bytes": compressed_bytes,
                    "data_url": data_url,
                }
            )

    has_visual_evidence = bool(combined_text or visual_frames)
    return {
        "status": "available" if has_visual_evidence else "absent",
        "source": "local_visual",
        "ocr": {
            "status": "available" if combined_text else "absent",
            "engine": "tesseract",
            "text": combined_text,
            "frames": ocr_entries,
            "unique_frames": unique_entries,
        },
        "frames": visual_frames,
    }


async def speech_analyze(path: Path) -> dict[str, Any]:
    # Frozen V1 architecture requires local speech/no-speech analysis.
    # This milestone intentionally does not call an external speech API.
    return {
        "status": "skipped_by_policy",
        "reason": "local speech analysis milestone pending",
        "source": "local_speech",
    }


def temp_workspace(prefix: str):
    return tempfile.TemporaryDirectory(prefix=prefix)
