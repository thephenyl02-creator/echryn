import asyncio
import base64
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import httpx

from app.config import settings


async def _run(*args: str) -> tuple[int, str, str]:
    p = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await p.communicate()
    return p.returncode, out.decode(errors="ignore"), err.decode(errors="ignore")


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
    # Periodic sampling is intentionally conservative and deterministic for v1.
    pattern = str(out_dir / "frame-%03d.jpg")
    code, _, err = await _run(
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
        "-vf", "fps=1/1.5,scale='min(960,iw)':-2", "-frames:v", str(max_frames),
        "-q:v", "3", pattern,
    )
    if code != 0:
        raise RuntimeError(f"ffmpeg frame extraction failed: {err[-500:]}")
    return sorted(out_dir.glob("frame-*.jpg"))


def image_data_url(path: Path) -> str:
    b64 = base64.b64encode(path.read_bytes()).decode()
    return f"data:image/jpeg;base64,{b64}"


async def vision_analyze(frames: list[Path]) -> dict[str, Any]:
    if not settings.vision_api_url:
        return {"status": "skipped_by_policy", "reason": "VISION_API_URL not configured"}
    payload = {
        "model": settings.vision_model,
        "task": "Extract on-screen creator text, UI/background text, scene meaning, actions, products/sites, and uncertainties. Return concise JSON.",
        "images": [image_data_url(p) for p in frames],
    }
    headers = {"Content-Type": "application/json"}
    if settings.vision_api_key:
        headers["Authorization"] = f"Bearer {settings.vision_api_key}"
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(settings.vision_api_url, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    return {"status": "available", "value": data, "source": "hosted_vision"}


async def speech_analyze(path: Path) -> dict[str, Any]:
    if not settings.speech_api_url:
        return {"status": "skipped_by_policy", "reason": "SPEECH_API_URL not configured"}
    headers = {}
    if settings.speech_api_key:
        headers["Authorization"] = f"Bearer {settings.speech_api_key}"
    files = {"file": (path.name, path.open("rb"), "video/mp4")}
    data = {"model": settings.speech_model or ""}
    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.post(settings.speech_api_url, files=files, data=data, headers=headers)
        r.raise_for_status()
        payload = r.json()
    text = payload.get("text") if isinstance(payload, dict) else None
    if not text:
        return {"status": "no_speech_detected", "value": payload, "source": "hosted_speech"}
    return {"status": "available", "value": payload, "source": "hosted_speech"}


def temp_workspace(prefix: str):
    return tempfile.TemporaryDirectory(prefix=prefix)
