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
    title="Extract Instagram Reel",
    description=(
        "Use when the user provides a public Instagram Reel URL and wants to understand "
        "the Reel's actual content. Retrieves public Reel metadata and, when needed, "
        "representative visual frames plus speech or transcript evidence. "
        "IMPORTANT VISUAL-EVIDENCE PROCEDURE: When visual.frames contains HTTPS URLs, "
        "retrieve and visually inspect each returned image using an image-capable retrieval "
        "tool before explaining on-screen content or fact-checking claims. These URL values "
        "identify actual WebP frame files; the JSON itself does not contain the images. "
        "Do not treat the mere presence of frame URLs as proof that the images were viewed. "
        "If image retrieval is unavailable or fails, explicitly disclose that the frames "
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
