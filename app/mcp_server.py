from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

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
