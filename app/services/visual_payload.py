"""Deliver one stored visual asset as typed MCP image content on demand."""
import base64
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from mcp.types import ImageContent, TextContent
from app.config import settings

_MIMES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
_MAX_BYTES = 8 * 1024 * 1024


def make_visual_contents(result: dict, asset_index: int = 1) -> list[TextContent | ImageContent]:
    visual = result.get("visual") or {}
    slides = visual.get("images") or []
    frames = visual.get("frames") or []
    assets = slides or frames

    def unavailable(reason: str) -> list[TextContent]:
        return [TextContent(type="text", text=json.dumps(
            {"status": "unavailable", "reason": reason, "asset_index": asset_index}
        ))]

    if not assets:
        return unavailable("no_visual_assets")
    if not 1 <= asset_index <= len(assets):
        return unavailable("asset_index_out_of_range")

    extraction_id = str(result.get("id") or "")
    if not re.fullmatch(r"[a-f0-9]{20}", extraction_id):
        return unavailable("invalid_extraction_id")
    asset = assets[asset_index - 1]
    filename = Path(urlparse(str(asset.get("url") or "")).path).name
    if not re.fullmatch(r"(?:slide|frame)-[0-9]{3}\.(?:jpg|jpeg|png|webp)", filename):
        return unavailable("invalid_filename")
    mime = _MIMES.get(Path(filename).suffix.lower())
    if mime != asset.get("mime_type"):
        return unavailable("mime_mismatch")
    root = settings.data_dir / settings.echryn_frame_store_subdir / extraction_id
    file = (root / filename).resolve()
    if not file.is_relative_to(root.resolve()) or not file.is_file():
        return unavailable("asset_not_in_evidence_store")
    if not 0 < file.stat().st_size <= _MAX_BYTES:
        return unavailable("asset_size_out_of_range")
    raw = file.read_bytes()
    identity = {"status": "available", "kind": "carousel_slide" if slides else "reel_frame",
                "asset_index": asset_index, "asset_count": len(assets), "mime_type": mime,
                "width": asset.get("width"), "height": asset.get("height")}
    identity["slide_index" if slides else "timestamp_seconds"] = (
        asset.get("slide_index") if slides else asset.get("timestamp_seconds")
    )
    return [
        TextContent(type="text", text=json.dumps(identity)),
        ImageContent(type="image", mimeType=mime, data=base64.b64encode(raw).decode("ascii")),
    ]
def make_all_visual_contents(result: dict, public_result: dict) -> list[TextContent | ImageContent]:
    """Return metadata, signed URLs, and all available image blocks together."""
    blocks: list[TextContent | ImageContent] = [
        TextContent(type="text", text=json.dumps(public_result, ensure_ascii=False))
    ]
    visual = result.get("visual") or {}
    assets = (visual.get("images") or []) or (visual.get("frames") or [])
    delivered = 0
    max_total_bytes = 16 * 1024 * 1024
    total_bytes = 0
    for index in range(1, len(assets) + 1):
        pair = make_visual_contents(result, index)
        if len(pair) > 1 and isinstance(pair[1], ImageContent):
            byte_count = len(pair[1].data) * 3 // 4
            if total_bytes + byte_count > max_total_bytes:
                blocks.append(TextContent(type="text", text=json.dumps({
                    "image_data_status": "size_budget_reached",
                    "first_undelivered_index": index,
                    "remaining_assets_have_signed_urls": True,
                })))
                break
            blocks.extend(pair)
            delivered += 1
            total_bytes += byte_count
        else:
            blocks.extend(pair)
    blocks.append(TextContent(type="text", text=json.dumps({
        "image_data_status": "complete" if delivered == len(assets) else "partial",
        "image_blocks": delivered, "total_assets": len(assets),
        "signed_urls_preserved": True,
    })))
    return blocks
