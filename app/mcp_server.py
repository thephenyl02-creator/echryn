from typing import Literal

from mcp.server.fastmcp import FastMCP

from app.services.extractor import Extractor

mcp = FastMCP(
    name="Echryn",
    stateless_http=True,
    json_response=True,
)

extractor = Extractor()


@mcp.tool()
async def extract_reel(
    url: str,
    mode: Literal["metadata", "auto", "evidence", "deep"] = "auto",
) -> dict:
    """
    Extract structured information and evidence from an Instagram Reel URL.

    Returns native metadata, semantic coverage information, visual evidence,
    speech/transcript evidence, media details, summary, provenance, and diagnostics.
    """
    return await extractor.extract(
        url,
        mode,
        True,
        "urls",
        False,
    )
