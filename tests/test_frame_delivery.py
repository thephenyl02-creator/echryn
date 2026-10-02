from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from PIL import Image

from app.services.media import (
    build_frame_url,
    cleanup_stale_frame_evidence,
    local_visual_analyze,
    refresh_frame_urls,
    validate_frame_signature,
)


def _make_frame(path: Path, split: int) -> None:
    image = Image.new("RGB", (64, 64), color=(20, 20, 20))
    for x in range(split, 64):
        for y in range(64):
            image.putpixel((x, y), (230, 230, 230))
    image.save(path)


def test_signed_frame_url_round_trip(monkeypatch):
    from app.services import media

    monkeypatch.setattr(media.settings, "echryn_api_key", "test-secret")
    monkeypatch.setattr(media.settings, "echryn_public_base_url", "http://localhost:8080")
    monkeypatch.setattr(media.settings, "echryn_frame_url_ttl_seconds", 600)

    url = build_frame_url("abc123", "frame-000.webp", now=1000)
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.path == "/v1/frames/abc123/frame-000.webp"
    assert validate_frame_signature(
        "abc123",
        "frame-000.webp",
        int(query["exp"][0]),
        query["sig"][0],
        now=1200,
    )
    assert not validate_frame_signature(
        "abc123",
        "frame-000.webp",
        int(query["exp"][0]),
        query["sig"][0],
        now=2000,
    )


@pytest.mark.asyncio
async def test_url_frame_delivery_persists_webp(tmp_path, monkeypatch):
    from app.services import media

    monkeypatch.setattr(media.settings, "echryn_data_dir", str(tmp_path / "data"))
    monkeypatch.setattr(media.settings, "echryn_api_key", "test-secret")
    monkeypatch.setattr(media.settings, "echryn_public_base_url", "http://localhost:8080")

    frames = []
    for index, split in enumerate((12, 20, 28, 36)):
        path = tmp_path / f"frame-{index:03d}-t{index * 1.25:.3f}.jpg"
        _make_frame(path, split)
        frames.append(path)

    result = await local_visual_analyze(
        frames,
        frame_delivery="urls",
        extraction_id="extract123",
        run_ocr=False,
    )

    assert result["status"] == "available"
    assert result["frames"]
    for frame in result["frames"]:
        assert frame["delivery"] == "url"
        assert "url" in frame
        assert "data_url" not in frame

        filename = urlparse(frame["url"]).path.rsplit("/", 1)[-1]
        stored = tmp_path / "data" / media.settings.echryn_frame_store_subdir / "extract123" / filename
        assert stored.is_file()
        assert stored.stat().st_size == frame["compressed_bytes"]


@pytest.mark.asyncio
async def test_inline_frame_delivery_still_supported(tmp_path):
    frame = tmp_path / "frame-000-t0.000.jpg"
    _make_frame(frame, 32)

    result = await local_visual_analyze(
        [frame],
        frame_delivery="inline",
        extraction_id="unused",
        run_ocr=False,
    )

    payload = result["frames"][0]
    assert payload["delivery"] == "inline"
    assert payload["data_url"].startswith("data:image/webp;base64,")
    assert "url" not in payload


@pytest.mark.asyncio
async def test_none_frame_delivery_returns_no_frames(tmp_path):
    frame = tmp_path / "frame-000-t0.000.jpg"
    _make_frame(frame, 32)

    result = await local_visual_analyze(
        [frame],
        frame_delivery="none",
        extraction_id="unused",
        run_ocr=False,
    )

    assert result["frames"] == []


def test_refresh_cached_frame_urls_reissues_signature(monkeypatch):
    from app.services import media

    monkeypatch.setattr(media.settings, "echryn_api_key", "test-secret")
    monkeypatch.setattr(media.settings, "echryn_public_base_url", "https://api.example.com")
    monkeypatch.setattr(media.settings, "echryn_frame_url_ttl_seconds", 600)

    result = {
        "id": "extract123",
        "visual": {
            "frames": [
                {
                    "frame_index": 2,
                    "delivery": "url",
                    "filename": "frame-002.webp",
                    "url": "https://old.example/frame-002.webp?exp=1&sig=old",
                }
            ]
        },
    }

    refresh_frame_urls(result)
    url = result["visual"]["frames"][0]["url"]

    assert url.startswith("https://api.example.com/v1/frames/extract123/frame-002.webp?")
    assert "sig=old" not in url


def test_cleanup_stale_frame_evidence(tmp_path, monkeypatch):
    import os
    from app.services import media

    monkeypatch.setattr(media.settings, "echryn_data_dir", str(tmp_path))
    root = tmp_path / media.settings.echryn_frame_store_subdir
    old_dir = root / "old"
    fresh_dir = root / "fresh"
    old_dir.mkdir(parents=True)
    fresh_dir.mkdir(parents=True)

    now = 10_000.0
    os.utime(old_dir, (now - 1000, now - 1000))
    os.utime(fresh_dir, (now - 10, now - 10))

    removed = cleanup_stale_frame_evidence(100, now=now)

    assert removed == 1
    assert not old_dir.exists()
    assert fresh_dir.exists()
