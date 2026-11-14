"""Deliver Instagram carousel slides via the same signed media URLs as Reel frames."""
import asyncio
import os
import uuid
from io import BytesIO
from urllib.parse import urlparse

import httpx
from PIL import Image

from app.config import settings
from app.services.media import build_frame_url

MAX_SLIDE_BYTES = 16 * 1024 * 1024
MAX_SLIDE_PIXELS = 25_000_000
IMAGE_FORMATS = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
}


def _instagram_media_host(url: str) -> bool:
    """Never proxy arbitrary URLs supplied through Instagram metadata."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        return (
            parsed.scheme == "https"
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
            and any(host == base or host.endswith("." + base)
                    for base in ("cdninstagram.com", "fbcdn.net"))
        )
    except (TypeError, ValueError):
        return False


async def _download_carousel_image(url: str) -> bytes:
    if not _instagram_media_host(url):
        raise ValueError("untrusted_image_host")
    headers = {
        "User-Agent": settings.instagram_user_agent,
        "Referer": "https://www.instagram.com/",
        "Accept": "image/jpeg,image/png,image/webp,*/*;q=0.5",
    }
    chunks = []
    size = 0
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        async with client.stream("GET", url, headers=headers) as response:
            response.raise_for_status()
            if response.status_code in (301, 302, 303, 307, 308):
                raise ValueError("image_redirect_not_supported")
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_SLIDE_BYTES:
                    raise ValueError("carousel_slide_too_large")
                chunks.append(chunk)
    if not size:
        raise ValueError("empty_carousel_slide")
    return b"".join(chunks)


def _store_slide_bytes(raw: bytes, extraction_id: str, slide_index: int) -> dict:
    # Verify the bytes are a real image; preserve original resolution and encoding.
    with Image.open(BytesIO(raw)) as im:
        if im.format not in IMAGE_FORMATS:
            raise ValueError("unsupported_carousel_image_format")
        width, height = im.size
        if not width or not height or width * height > MAX_SLIDE_PIXELS:
            raise ValueError("invalid_carousel_image_dimensions")
        extension, mime_type = IMAGE_FORMATS[im.format]
        im.load()

    root = settings.data_dir / settings.echryn_frame_store_subdir / extraction_id
    root.mkdir(parents=True, exist_ok=True)
    filename = f"slide-{slide_index:03d}.{extension}"
    destination = root / filename
    temporary = root / f".{filename}.{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_bytes(raw)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "url": build_frame_url(extraction_id, filename),
        "filename": filename,
        "mime_type": mime_type,
        "width": width,
        "height": height,
        "bytes": len(raw),
        "delivery": "url",
    }


async def deliver_carousel_images(images: list[dict], extraction_id: str) -> tuple[list[dict], list[dict]]:
    """Deliver in slide order; individual fetch failures do not discard other slides."""
    semaphore = asyncio.Semaphore(4)

    async def deliver(entry: dict) -> tuple[dict, dict | None]:
        item = dict(entry)
        upstream_url = item.pop("url", None)
        index = item["slide_index"]
        item["url"] = None
        if not upstream_url:
            return item, {"slide_index": index, "reason": "image_url_unavailable"}
        try:
            async with semaphore:
                raw = await _download_carousel_image(upstream_url)
                stored = await asyncio.to_thread(_store_slide_bytes, raw, extraction_id, index)
            item.update(stored)
            return item, None
        except (ValueError, OSError, httpx.HTTPError, Image.DecompressionBombError) as exc:
            # Never expose CDN query tokens or other sensitive URL details in errors.
            reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            return item, {"slide_index": index, "reason": reason}

    outcomes = await asyncio.gather(*(deliver(entry) for entry in images))
    return [image for image, _ in outcomes], [error for _, error in outcomes if error]
