import io
import pytest
from PIL import Image
from app.services.extractor import Extractor
from app.services import extractor as extractor_module, carousel_delivery
from app.services.url_security import trusted_instagram_media_url, trusted_text_track_url
from app.adapters.instagram import resolve_instagram_url


@pytest.mark.asyncio
async def test_auto_text_sufficient_skips_video_download(tmp_path, monkeypatch):
    monkeypatch.setattr(extractor_module.settings, "echryn_data_dir", str(tmp_path))
    item = {"media_type": 2, "caption": {"text": "This video explains how abandoned patents can be searched, summarized, reinvented with AI and compared against competitors."},
            "video_versions": [{"url": "https://scontent.cdninstagram.com/clip.mp4", "width": 500, "height": 500}]}
    x = Extractor()
    async def info(_):
        return {"items": [item]}
    async def unexpected(*args, **kwargs):
        raise AssertionError("Should not download video with sufficient caption")
    monkeypatch.setattr(x.instagram, "media_info", info)
    monkeypatch.setattr(extractor_module, "download_media", unexpected)
    result = await x.extract("https://www.instagram.com/reel/DfYZz1uk0IP/", mode="auto", multimodal=True)
    assert result["status"] == "complete", result.get("error")
    assert result["diagnostics"]["mode"] == "auto"
    assert result["visual"]["status"] == "not_applicable"

@pytest.mark.asyncio
async def test_auto_photo_delivers_actual_image(tmp_path, monkeypatch):
    monkeypatch.setattr(extractor_module.settings, "echryn_data_dir", str(tmp_path))
    item = {"media_type": 1, "caption": {"text": "A photograph of an unusual place."},
            "image_versions2": {"candidates": [{"url": "https://scontent.cdninstagram.com/photo.jpg", "width": 300, "height": 400}]}}
    raw = io.BytesIO()
    Image.new("RGB", (35, 50)).save(raw, "JPEG")
    async def info(_):
        return {"items": [item]}
    async def download(_):
        return raw.getvalue()
    x = Extractor()
    monkeypatch.setattr(x.instagram, "media_info", info)
    monkeypatch.setattr(carousel_delivery, "_download_carousel_image", download)
    r = await x.extract("https://www.instagram.com/p/DfpwJ4GjdXS/", mode="auto", multimodal=True)
    assert r["visual"]["media_type"] == "photo"
    assert len([im for im in r["visual"]["images"] if im["url"]]) == 1


def test_host_and_instagram_url_security():
    assert trusted_instagram_media_url("https://scontent.cdninstagram.com/abc.jpg")
    assert trusted_text_track_url("https://www.instagram.com/native.vtt")
    for url in ("http://scontent.cdninstagram.com/x.mp4",
                "https://cdninstagram.com.evil.net/x.mp4",
                "https://127.0.0.1/private",
                "https://scontent.cdninstagram.com:8443/x.mp4"):
        assert not trusted_instagram_media_url(url)
    for url in ("http://www.instagram.com/p/abc/", "https://user@www.instagram.com/p/abc/",
                "https://www.instagram.com:444/p/abc/"):
        with pytest.raises(ValueError):
            resolve_instagram_url(url)

@pytest.mark.asyncio
async def test_video_download_denies_untrusted_hosts_before_http(tmp_path):
    from app.services.media import download_media
    for url in ("http://scontent.cdninstagram.com/a.mp4",
                "https://127.0.0.1/admin",
                "https://cdninstagram.com.attacker.test/a.mp4"):
        with pytest.raises(ValueError, match="untrusted_video_media_host"):
            await download_media(url, tmp_path / "video.mp4")


@pytest.mark.asyncio
async def test_text_track_denies_external_host():
    from app.services.native_resources import fetch_text_track_evidence
    r = await fetch_text_track_evidence(
        [{"url": "https://127.0.0.1:443/private.vtt"}], user_agent="test",
    )
    assert r["semantic_coverage"] is False
    assert r["tracks"][0]["status"] == "failed"


@pytest.mark.asyncio
async def test_invalid_frame_id_is_rejected():
    from fastapi import HTTPException
    from app.main import get_frame
    with pytest.raises(HTTPException) as exc:
        await get_frame("..", "slide-001.jpg", exp=2147483647, sig="invalid")
    assert exc.value.status_code == 400

def test_rest_api_rejects_missing_key(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.config import settings
    monkeypatch.setattr(settings, "echryn_api_key", "known-test-secret")
    client = TestClient(app)
    r = client.post("/v1/extractions/sync", json={
        "url": "https://www.instagram.com/reel/DfYZz1uk0IP/",
        "mode": "metadata",
    })
    assert r.status_code == 401

@pytest.mark.asyncio
async def test_mcp_auto_text_only_and_visual_escalation(monkeypatch):
    import json
    from app import mcp_server
    modes = []
    async def fake_extract(url, mode, multimodal, frame_delivery, force_refresh):
        modes.append(mode)
        return {"status": "complete", "source": {"shortcode": "test"},
                "native": {"caption": "Enough written context"},
                "visual": {"status": "not_applicable", "images": [], "frames": []},
                "speech": {"status": "not_applicable"}, "summary": {"text": "Enough written context"}}
    monkeypatch.setattr(mcp_server.extractor, "extract", fake_extract)
    blocks = await mcp_server.extract_reel("https://www.instagram.com/reel/DfYZz1uk0IP/")
    assert len(blocks) == 1 and blocks[0].type == "text"
    assert json.loads(blocks[0].text)["visual"]["delivery"] == "none"
    assert "mode='evidence'" in json.loads(blocks[0].text)["visual"]["instruction"]
    assert modes == ["auto"]
