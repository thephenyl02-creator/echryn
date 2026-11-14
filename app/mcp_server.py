from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from app.services.extractor import Extractor

mcp = FastMCP(
    name="Echryn",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            "echryn.fenilbuilds.com",
            "echryn.fenilbuilds.com:*",
            "echryn-4h6me7nata-ue.a.run.app",
            "echryn-4h6me7nata-ue.a.run.app:*",
            "echryn-427757463777.us-east1.run.app",
            "echryn-427757463777.us-east1.run.app:*",
            "localhost:*",
            "127.0.0.1:*",
        ],
    ),
)

extractor = Extractor()


def _public_result(result: dict) -> dict:
    source = result.get("source") or {}
    author = result.get("author") or {}
    native = result.get("native") or {}
    music = native.get("music") or {}
    music_asset = music.get("music_asset_info") or {}

    frames = []
    for frame in ((result.get("visual") or {}).get("frames") or []):
        frames.append(
            {
                "timestamp_seconds": frame.get("timestamp_seconds"),
                "mime_type": frame.get("mime_type"),
                "width": frame.get("width"),
                "height": frame.get("height"),
                "url": frame.get("url"),
            }
        )

    visual = result.get("visual") or {}
    images = [
        {key: entry.get(key) for key in
         ("slide_index", "kind", "url", "width", "height", "accessibility_caption")}
        for entry in visual.get("images") or [] if entry.get("url")
    ]
    native_public = {
        "caption": native.get("caption"),
        "like_count": native.get("like_count"),
        "comment_count": native.get("comment_count"),
        "play_count": native.get("play_count"),
        "duration_seconds": native.get("duration_seconds"),
        "is_ai_generated": native.get("is_ai_generated"),
    }
    if music_asset:
        native_public["music"] = {
            "title": music_asset.get("title"),
            "artist": music_asset.get("display_artist"),
            "is_explicit": music_asset.get("is_explicit"),
        }

    return {
        "status": result.get("status"),
        "source": {
            "platform": source.get("platform"),
            "shortcode": source.get("shortcode"),
            "canonical_url": source.get("canonical_url"),
        },
        "author": {
            "username": author.get("username"),
            "full_name": author.get("full_name"),
            "verified": author.get("verified"),
        },
        "native": native_public,
        "visual": {
            "status": (result.get("visual") or {}).get("status"),
            "requires_visual_inspection": bool(frames or images or visual.get("media_type") == "carousel"),
            "instruction": (
                "Retrieve and visually inspect each frame URL with an image-capable tool "
                "before interpreting on-screen content. If retrieval is unavailable, "
                "disclose that the frames were not inspected; do not infer their contents "
                "from the caption or metadata."
                if frames else (
                    "Retrieve all carousel image URLs in slide order; inspect images before making visual claims. "
                    "Alt descriptions and caption alone are not visual evidence. Report missing URLs."
                    if visual.get("media_type") == "carousel" else None
                )
            ),
            "media_type": visual.get("media_type"),
            "slide_count": visual.get("slide_count"),
            "missing_slides": visual.get("missing_slides", []),
            "images": images,
            "frames": frames,
        },
        "speech": result.get("speech"),
        "summary": result.get("summary"),
        "provenance": result.get("provenance"),
        "diagnostics": {
            "mode": (result.get("diagnostics") or {}).get("mode"),
            "semantic_coverage": (result.get("diagnostics") or {}).get("semantic_coverage"),
        },
    }


@mcp.tool(
    title="Extract Instagram Media",
    description=(
        "Use when the user provides an Instagram Reel, image post, or carousel and wants to understand "
        "its actual content. Retrieves post metadata, original carousel slide image URLs and, when needed, "
        "representative visual frames plus speech or transcript evidence. "
        "IMPORTANT VISUAL-EVIDENCE PROCEDURE: When visual.images or visual.frames contains HTTPS URLs, "
        "retrieve and visually inspect each returned image using an image-capable retrieval "
        "tool before explaining on-screen content or fact-checking claims. These URL values "
        "identify original carousel images or generated WebP frames; the JSON does not contain images. "
        "Do not treat the mere presence of frame URLs as proof that the images were viewed. "
        "If image retrieval is unavailable or fails, explicitly disclose that the visuals "
        "were not inspected and avoid unsupported visual claims. "
        "This is read-only and does not post, modify, or delete Instagram content."
    ),
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        open_world_hint=True,
    ),
)
async def extract_reel(
    url: str,
    mode: Literal["metadata", "auto", "evidence", "deep"] = "auto",
) -> dict:
    result = await extractor.extract(
        url,
        mode,
        True,
        "urls",
        False,
    )
    return _public_result(result)
