import asyncio
from mcp.server.fastmcp import FastMCP
from app.services.extractor import Extractor

mcp = FastMCP("Echryn")
extractor = Extractor()


@mcp.tool()
async def extract_url(url: str, mode: str = "auto", force_refresh: bool = False) -> dict:
    """Extract structured information from a short-form content URL. Instagram Reels are supported in v1."""
    return await extractor.extract(url, mode=mode, force_refresh=force_refresh)


@mcp.tool()
def service_info() -> dict:
    """Return Echryn service capabilities."""
    return {
        "name": "Echryn",
        "launch_product": "Reels API",
        "tagline": "The API for short-form content.",
        "supported_sources": ["instagram_reel"],
        "modes": ["metadata", "auto", "deep"],
    }


if __name__ == "__main__":
    mcp.run()
