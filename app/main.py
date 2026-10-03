import os
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, ORJSONResponse, PlainTextResponse

from app.config import settings
from app.models.schemas import ExtractionAccepted, ExtractionRequest, ExtractionResult
from app.services.extractor import Extractor
from app.services.media import validate_frame_signature
from app.mcp_server import mcp

mcp.settings.streamable_http_path = "/"
mcp_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(
    title="Echryn — Reels API",
    description="Echryn — The API for short-form content.",
    version="0.1.0",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)

app.mount("/mcp", mcp_app)
extractor = Extractor()
RESULTS: dict[str, dict] = {}


def require_api_key(x_api_key: str | None = Header(default=None)):
    configured = settings.echryn_api_key
    if configured and configured != "change-me" and x_api_key != configured:
        raise HTTPException(status_code=401, detail="Invalid API key")


@app.get("/", response_class=HTMLResponse)
async def homepage():
    return """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Echryn — Reels API</title>
  <style>
    body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;max-width:760px;margin:64px auto;padding:0 24px;line-height:1.55;color:#171717}
    h1{font-size:2.4rem;margin-bottom:.25rem} .muted{color:#666} a{color:inherit}
    code{background:#f4f4f4;padding:.15rem .35rem;border-radius:.3rem}
    nav{display:flex;gap:18px;flex-wrap:wrap;margin-top:28px}
  </style>
</head>
<body>
  <h1>Echryn</h1>
  <p class="muted">The API for short-form content.</p>
  <p>Echryn turns an Instagram Reel URL into structured metadata and media evidence that AI systems can interpret, including representative visual frames and speech/transcript evidence when available.</p>
  <p>Public MCP endpoint: <code>https://echryn.fenilbuilds.com/mcp/</code></p>
  <nav>
    <a href="/privacy">Privacy</a>
    <a href="/terms">Terms</a>
    <a href="/support">Support</a>
    <a href="/health">Status</a>
  </nav>
</body>
</html>
"""


@app.get("/privacy", response_class=HTMLResponse)
async def privacy():
    return """
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Echryn Privacy Policy</title><style>body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;max-width:800px;margin:56px auto;padding:0 24px;line-height:1.6;color:#171717}h1,h2{line-height:1.2}</style></head>
<body>
<h1>Echryn Privacy Policy</h1>
<p>Effective: October 3, 2026</p>
<p>Echryn processes URLs that users explicitly provide in order to retrieve and interpret publicly accessible short-form content. The service may process public post metadata, captions, engagement counts, audio information, representative video frames, and speech/transcript evidence.</p>
<h2>Data handling</h2>
<p>Downloaded media is used for extraction and is designed to be temporary. Structured extraction results and derived frame artifacts may be cached transiently for performance and reliability. Hosting infrastructure may generate operational logs containing request timing, network or IP metadata, status codes, and error information. These logs are used for security, debugging, and service reliability, not behavioral advertising or profiling.</p>
<h2>Accounts and authentication</h2>
<p>The current public Echryn MCP tool does not require an Echryn user account. Authentication and account features may be added in the future, with this policy updated before they are required.</p>
<h2>Sharing and sale</h2>
<p>Echryn does not sell personal data. Data may be processed by infrastructure providers required to operate the service and by the public content platform necessary to retrieve the URL a user asks Echryn to analyze.</p>
<h2>User responsibility</h2>
<p>Users should submit only URLs they are authorized to access and should not use Echryn to obtain private or restricted content.</p>
<h2>Contact</h2>
<p>Privacy questions can be sent to the developer contact listed on the Echryn support page.</p>
</body></html>
"""


@app.get("/terms", response_class=HTMLResponse)
async def terms():
    return """
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Echryn Terms of Service</title><style>body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;max-width:800px;margin:56px auto;padding:0 24px;line-height:1.6;color:#171717}h1,h2{line-height:1.2}</style></head>
<body>
<h1>Echryn Terms of Service</h1>
<p>Effective: October 3, 2026</p>
<p>Echryn provides automated extraction and interpretation support for short-form content URLs. By using Echryn, you agree to use it lawfully and only with content you are permitted to access.</p>
<h2>No guarantee of completeness</h2>
<p>Extraction depends on source availability, public metadata, media accessibility, and automated analysis. Results may be incomplete, delayed, or inaccurate and should be independently verified when important decisions depend on them.</p>
<h2>Acceptable use</h2>
<p>Do not use Echryn to bypass access controls, retrieve private content, violate platform terms or applicable law, infringe intellectual property rights, or conduct abusive automated traffic.</p>
<h2>Availability</h2>
<p>The service may be changed, rate-limited, suspended, or discontinued. Public anonymous access may later be supplemented or replaced by authenticated access.</p>
<h2>Third-party content</h2>
<p>Content remains subject to the rights and terms of its original platform and rights holders. Echryn does not claim ownership of third-party content.</p>
<h2>Contact</h2>
<p>Questions about these terms can be sent to the developer contact listed on the Echryn support page.</p>
</body></html>
"""


@app.get("/support", response_class=HTMLResponse)
async def support():
    return """
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Echryn Support</title><style>body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;max-width:760px;margin:56px auto;padding:0 24px;line-height:1.6;color:#171717}</style></head>
<body>
<h1>Echryn Support</h1>
<p>For support, bug reports, privacy questions, or plugin review questions, contact:</p>
<p><a href="mailto:the.phenyl02@gmail.com">the.phenyl02@gmail.com</a></p>
<p>When reporting an extraction problem, include the public Reel URL and a short description of what failed. Do not send passwords, session cookies, API keys, or other secrets.</p>
</body></html>
"""


@app.get("/.well-known/openai-apps-challenge", response_class=PlainTextResponse)
async def openai_apps_challenge():
    token = os.getenv("OPENAI_APPS_CHALLENGE_TOKEN", "").strip()
    if not token:
        raise HTTPException(status_code=404, detail="Challenge token not configured")
    return token


@app.get("/health")
@app.get("/healthz")
async def healthz():
    return {"ok": True, "service": "echryn", "version": "0.1.0"}


async def _run_extract(req: ExtractionRequest):
    result = await extractor.extract(
        str(req.url),
        req.mode,
        req.multimodal,
        req.frame_delivery,
        req.force_refresh,
    )
    RESULTS[result["id"]] = result


@app.post("/v1/extractions", response_model=ExtractionAccepted, dependencies=[Depends(require_api_key)])
async def create_extraction(req: ExtractionRequest, background: BackgroundTasks):
    resolved = __import__("app.adapters.instagram", fromlist=["resolve_instagram_url"]).resolve_instagram_url(str(req.url))
    _, _, request_id = extractor.request_keys(
        resolved,
        req.mode,
        req.multimodal,
        req.frame_delivery,
    )
    cached = None
    if not req.force_refresh:
        cached = extractor.get_cached_result(
            resolved,
            req.mode,
            req.multimodal,
            req.frame_delivery,
        )
    if cached:
        RESULTS[request_id] = cached
        return ExtractionAccepted(id=request_id, status="complete", cached=True)
    RESULTS[request_id] = {"id": request_id, "status": "processing"}
    background.add_task(_run_extract, req)
    return ExtractionAccepted(id=request_id, status="queued", cached=False)


@app.post("/v1/extractions/sync", response_model=ExtractionResult, dependencies=[Depends(require_api_key)])
async def create_extraction_sync(req: ExtractionRequest):
    result = await extractor.extract(
        str(req.url),
        req.mode,
        req.multimodal,
        req.frame_delivery,
        req.force_refresh,
    )
    if result["status"] == "failed":
        raise HTTPException(status_code=502, detail=result)
    RESULTS[result["id"]] = result
    return result


@app.get("/v1/extractions/{extraction_id}", dependencies=[Depends(require_api_key)])
async def get_extraction(extraction_id: str):
    result = RESULTS.get(extraction_id)
    if not result:
        raise HTTPException(status_code=404, detail="Extraction not found in this process")
    return result


@app.get("/v1/frames/{extraction_id}/{filename}")
async def get_frame(extraction_id: str, filename: str, exp: int, sig: str):
    if "/" in filename or "\\" in filename or not filename.endswith(".webp"):
        raise HTTPException(status_code=400, detail="Invalid frame filename")

    if not validate_frame_signature(extraction_id, filename, exp, sig):
        raise HTTPException(status_code=403, detail="Invalid or expired frame URL")

    frame_root = settings.data_dir / settings.echryn_frame_store_subdir / extraction_id
    frame_path = (frame_root / filename).resolve()
    try:
        frame_path.relative_to(frame_root.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid frame path")

    if not frame_path.is_file():
        raise HTTPException(status_code=404, detail="Frame not found")

    return FileResponse(frame_path, media_type="image/webp")
