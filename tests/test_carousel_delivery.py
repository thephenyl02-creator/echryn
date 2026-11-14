from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from PIL import Image

from app.services import carousel_delivery
from app.services.media import refresh_frame_urls, validate_frame_signature


def _jpeg() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (55, 70), (30, 60, 120)).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_trusted_instagram_cdn_only():
    check = carousel_delivery._instagram_media_host
    assert check("https://scontent-atl3-2.cdninstagram.com/v/t51/file.jpg?sig=x")
    assert check("https://scontent.fna.fbcdn.net/media/image.jpg")
    assert not check("http://scontent-atl3-2.cdninstagram.com/a.jpg")
    assert not check("https://cdninstagram.com.evil.org/a.jpg")
    assert not check("https://127.0.0.1/a.jpg")
    assert not check("https://scontent.cdninstagram.com:8080/a.jpg")


@pytest.mark.asyncio
async def test_all_twelve_slides_signed_and_original_bytes_preserved(tmp_path, monkeypatch):
    monkeypatch.setattr(carousel_delivery.settings, "echryn_data_dir", str(tmp_path))
    monkeypatch.setattr(carousel_delivery.settings, "echryn_public_base_url",
                        "https://echryn.fenilbuilds.com")
    monkeypatch.setattr(carousel_delivery.settings, "echryn_api_key", "test-secret")
    original = _jpeg()
    async def download(url):
        assert url.startswith("https://scontent.cdninstagram.com/")
        return original
    monkeypatch.setattr(carousel_delivery, "_download_carousel_image", download)
    items = [{"slide_index": i, "kind": "image",
              "url": f"https://scontent.cdninstagram.com/{i}.jpg"}
             for i in range(1, 13)]
    delivered, errors = await carousel_delivery.deliver_carousel_images(items, "extract123")
    assert not errors
    assert len(delivered) == 12
    assert [i["slide_index"] for i in delivered] == list(range(1, 13))
    for entry in delivered:
        assert entry["url"].startswith(
            "https://echryn.fenilbuilds.com/v1/frames/extract123/slide-")
        assert "cdninstagram" not in entry["url"]
        assert entry["mime_type"] == "image/jpeg"
        assert entry["width"] == 55 and entry["height"] == 70
        path = tmp_path / "frames" / "extract123" / entry["filename"]
        assert path.read_bytes() == original
        url = urlparse(entry["url"])
        qs = parse_qs(url.query)
        assert validate_frame_signature("extract123", entry["filename"],
                                        int(qs["exp"][0]), qs["sig"][0])

    stale = delivered[0]["url"]
    delivered[0]["url"] = "https://old.invalid/expired"
    refresh_frame_urls({"id": "extract123", "visual": {"images": delivered}})
    assert delivered[0]["url"] != "https://old.invalid/expired"
    assert delivered[0]["url"] == stale or "sig=" in delivered[0]["url"]


@pytest.mark.asyncio
async def test_partial_failures_report_missing_and_preserve_other_slides(tmp_path, monkeypatch):
    monkeypatch.setattr(carousel_delivery.settings, "echryn_data_dir", str(tmp_path))
    async def download(url):
        if "/2.jpg" in url:
            raise ValueError("image_redirect_not_supported")
        return _jpeg()
    monkeypatch.setattr(carousel_delivery, "_download_carousel_image", download)
    images = [{"slide_index": i, "url": f"https://scontent.cdninstagram.com/{i}.jpg"}
              for i in range(1, 4)]
    delivered, errors = await carousel_delivery.deliver_carousel_images(images, "partial")
    assert [bool(i["url"]) for i in delivered] == [True, False, True]
    assert errors == [{"slide_index": 2, "reason": "image_redirect_not_supported"}]


@pytest.mark.asyncio
async def test_signed_carousel_jpeg_is_served_by_existing_frame_route(tmp_path, monkeypatch):
    from app.main import get_frame
    monkeypatch.setattr(carousel_delivery.settings, "echryn_data_dir", str(tmp_path))
    monkeypatch.setattr(carousel_delivery.settings, "echryn_api_key", "test-secret")
    payload = carousel_delivery._store_slide_bytes(_jpeg(), "route123", 1)
    query = parse_qs(urlparse(payload["url"]).query)
    response = await get_frame("route123", "slide-001.jpg",
                               exp=int(query["exp"][0]), sig=query["sig"][0])
    assert response.media_type == "image/jpeg"
    assert Path(response.path).read_bytes() == _jpeg()
