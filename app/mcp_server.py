from mcp.server.fastmcp import FastMCP
from app.services.extractor import Extractor

mcp = FastMCP("Echryn")
extractor = Extractor()


@mcp.tool()
async def extract_url(
    url: str,
    mode: str = "auto",
    multimodal: bool = False,
    force_refresh: bool = False,
) -> dict:
    """Extract structured evidence from a short-form content URL. Instagram Reels are supported in v1."""
    return await extractor.extract(
        url,
        mode=mode,
        multimodal=multimodal,
        force_refresh=force_refresh,
    )


@mcp.tool()
def service_info() -> dict:
    """Return Echryn service capabilities."""
    return {
        "name": "Echryn",
        "launch_product": "Reels API",
        "tagline": "The API for short-form content.",
        "supported_sources": ["instagram_reel"],
        "modes": ["metadata", "auto", "evidence", "deep"],
        "multimodal_ocr_bypass": True,
        "local_audio": {
            "speech_detection": "silero_vad",
            "transcription": "faster_whisper",
            "licensed_music_policy": True,
        },
    }


if __name__ == "__main__":
    mcp.run()
