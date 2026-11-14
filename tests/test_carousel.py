import pytest
from app.adapters.instagram import normalize_native, extract_carousel_images
from app.mcp_server import _public_result
from app.services.extractor import Extractor


def make_item(n=12, missing=()):
    return {"media_type": 8, "carousel_media_count": n, "caption": {"text": "Long caption that should never block carousel image delivery."}, "carousel_media": [
        {"media_type": 1, "accessibility_caption": f"Slide {i+1}", "image_versions2": {"candidates": [] if i+1 in missing else [
            {"url": f"https://cdn.test/{i+1}-small.jpg", "width": 100, "height": 100},
            {"url": f"https://cdn.test/{i+1}.jpg", "width": 900, "height": 1200},
        ]}} for i in range(n)]}


def test_carousel_urls_all_twelve_and_order():
    data = normalize_native({"items": [make_item()]})["media"]["carousel"]
    assert data["slide_count"] == 12
    assert [v["url"] for v in data["images"]] == [f"https://cdn.test/{i}.jpg" for i in range(1, 13)]
    assert extract_carousel_images({"media_type": 2})["is_carousel"] is False


@pytest.mark.asyncio
async def test_auto_carousel_ignores_caption_and_reports_missing(tmp_path, monkeypatch):
    from app.storage import cache
    monkeypatch.setattr(cache.settings, "echryn_data_dir", str(tmp_path))
    x = Extractor()
    async def media_info(_):
        return {"items": [make_item(missing=(5, 9))]}
    monkeypatch.setattr(x.instagram, "media_info", media_info)
    r = await x.extract("https://www.instagram.com/p/Dfb2I2jn1KZ/", mode="auto", multimodal=True)
    out = _public_result(r)
    assert out["visual"]["status"] == "partial"
    assert out["visual"]["slide_count"] == 12
    assert out["visual"]["missing_slides"] == [5, 9]
    assert len(out["visual"]["images"]) == 10
    assert out["visual"]["requires_visual_inspection"] is True
    assert out["visual"]["frames"] == []
