import io
from urllib.parse import urlparse
from fastapi.testclient import TestClient
from PIL import Image

from app import main
from app.config import settings
from app.services.media import build_frame_url
from app.services import visual_payload


def test_signed_image_url_uses_shared_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "echryn_data_dir", str(tmp_path))
    image = Image.new("RGB", (24, 18), (11, 170, 75))
    stream = io.BytesIO()
    image.save(stream, "PNG")
    raw = stream.getvalue()
    monkeypatch.setattr(main, "fetch_frame", lambda e, f: raw)
    url = build_frame_url("a" * 20, "slide-001.png")
    with TestClient(main.app) as client:
        result = client.get(urlparse(url).path + "?" + urlparse(url).query)
    assert result.status_code == 200
    assert result.content == raw
    assert result.headers["content-type"] == "image/png"


def test_native_image_falls_back_to_shared_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "echryn_data_dir", str(tmp_path))
    monkeypatch.setattr(visual_payload, "fetch_frame", lambda e, f: b"abcde")
    result = {"id": "a" * 20, "visual": {"images": [{
        "url": build_frame_url("a" * 20, "slide-001.jpg"),
        "mime_type": "image/jpeg", "slide_index": 1,
    }]}}
    blocks = visual_payload.make_visual_contents(result, 1)
    assert [b.type for b in blocks] == ["text", "image"]
