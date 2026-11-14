import base64
from io import BytesIO

import pytest
from mcp.types import ImageContent, TextContent
from PIL import Image

from app.config import settings
from app.services.visual_payload import make_visual_contents
from app import mcp_server

ID = "a" * 20


def jpeg_bytes():
    out = BytesIO()
    Image.new("RGB", (48, 66), (20, 40, 60)).save(out, format="JPEG")
    return out.getvalue()


def stored_result(tmp_path, is_carousel=True):
    name = "slide-001.jpg" if is_carousel else "frame-000.jpg"
    media_type = "image/jpeg"
    folder = tmp_path / "frames" / ID
    folder.mkdir(parents=True, exist_ok=True)
    data = jpeg_bytes()
    (folder / name).write_bytes(data)
    item = {"url": "https://echryn.fenilbuilds.com/v1/frames/" + ID + "/" + name,
            "mime_type": media_type, "width": 48, "height": 66}
    item["slide_index" if is_carousel else "timestamp_seconds"] = 1 if is_carousel else 0.0
    return {"id": ID, "status": "complete", "visual": {
        "images": [item] if is_carousel else [],
        "frames": [] if is_carousel else [item]}}, data


@pytest.mark.parametrize("is_carousel", [True, False])
def test_inline_native_image_content(tmp_path, monkeypatch, is_carousel):
    monkeypatch.setattr(settings, "echryn_data_dir", str(tmp_path))
    result, data = stored_result(tmp_path, is_carousel)
    blocks = make_visual_contents(result, 1)
    assert isinstance(blocks[0], TextContent)
    assert isinstance(blocks[1], ImageContent)
    assert blocks[1].mimeType == "image/jpeg"
    assert base64.b64decode(blocks[1].data) == data


def test_inline_invalid_index_or_missing_media(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "echryn_data_dir", str(tmp_path))
    result, _ = stored_result(tmp_path)
    assert len(make_visual_contents(result, 2)) == 1
    (tmp_path / "frames" / ID / "slide-001.jpg").unlink()
    assert "asset_not_in_evidence_store" in make_visual_contents(result)[0].text


@pytest.mark.asyncio
async def test_mcp_image_tool_returns_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "echryn_data_dir", str(tmp_path))
    result, data = stored_result(tmp_path)
    calls = []
    async def fake_extract(url, mode, multimodal, frame_delivery, force_refresh):
        calls.append((mode, frame_delivery, force_refresh))
        return result
    monkeypatch.setattr(mcp_server.extractor, "extract", fake_extract)
    blocks = await mcp_server.get_visual_image("https://www.instagram.com/p/example/", 1)
    assert calls == [("evidence", "urls", False)]
    assert isinstance(blocks[1], ImageContent)
    assert base64.b64decode(blocks[1].data) == data
@pytest.mark.asyncio
async def test_mcp_protocol_tool_result_is_image_block(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "echryn_data_dir", str(tmp_path))
    result, data = stored_result(tmp_path)
    async def fake_extract(url, mode, multimodal, frame_delivery, force_refresh):
        return result
    monkeypatch.setattr(mcp_server.extractor, "extract", fake_extract)
    blocks = await mcp_server.mcp.call_tool(
        "get_visual_image", {"url": "https://www.instagram.com/p/test/", "asset_index": 1}
    )
    assert len(blocks) == 2
    assert blocks[0].type == "text"
    assert blocks[1].type == "image"
    assert base64.b64decode(blocks[1].data) == data


@pytest.mark.asyncio
@pytest.mark.parametrize("is_carousel", [True, False])
async def test_main_extract_returns_native_image_and_urls(tmp_path, monkeypatch, is_carousel):
    monkeypatch.setattr(settings, "echryn_data_dir", str(tmp_path))
    result, data = stored_result(tmp_path, is_carousel)
    calls = []
    async def fake_extract(url, mode, multimodal, frame_delivery, force_refresh):
        calls.append((mode, multimodal, frame_delivery, force_refresh))
        return result
    monkeypatch.setattr(mcp_server.extractor, "extract", fake_extract)
    blocks = await mcp_server.mcp.call_tool(
        "extract_reel", {"url": "https://www.instagram.com/p/test/"}
    )
    assert calls == [("auto", True, "urls", False)]
    assert blocks[0].type == "text"
    assert "https://echryn.fenilbuilds.com/v1/frames/" in blocks[0].text
    pictures = [b for b in blocks if b.type == "image"]
    assert len(pictures) == 1
    assert base64.b64decode(pictures[0].data) == data


@pytest.mark.asyncio
async def test_main_extract_url_only_mode_preserved(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "echryn_data_dir", str(tmp_path))
    result, _ = stored_result(tmp_path)
    async def fake_extract(url, mode, multimodal, frame_delivery, force_refresh):
        assert mode == "auto"
        return result
    monkeypatch.setattr(mcp_server.extractor, "extract", fake_extract)
    blocks = await mcp_server.mcp.call_tool(
        "extract_reel", {"url": "https://www.instagram.com/p/test/", "image_delivery": "urls"}
    )
    assert len(blocks) == 1
    assert blocks[0].type == "text"
    assert "slide-001.jpg" in blocks[0].text
