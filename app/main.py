from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from fastapi.responses import ORJSONResponse

from app.config import settings
from app.models.schemas import ExtractionAccepted, ExtractionRequest, ExtractionResult
from app.services.extractor import Extractor

app = FastAPI(
    title="Echryn — Reels API",
    description="Echryn — The API for short-form content.",
    version="0.1.0",
    default_response_class=ORJSONResponse,
)
extractor = Extractor()
RESULTS: dict[str, dict] = {}


def require_api_key(x_api_key: str | None = Header(default=None)):
    configured = settings.echryn_api_key
    if configured and configured != "change-me" and x_api_key != configured:
        raise HTTPException(status_code=401, detail="Invalid API key")


@app.get("/healthz")
async def healthz():
    return {"ok": True, "service": "echryn", "version": "0.1.0"}


async def _run_extract(req: ExtractionRequest):
    result = await extractor.extract(str(req.url), req.mode, req.force_refresh)
    RESULTS[result["id"]] = result


@app.post("/v1/extractions", response_model=ExtractionAccepted, dependencies=[Depends(require_api_key)])
async def create_extraction(req: ExtractionRequest, background: BackgroundTasks):
    resolved = __import__("app.adapters.instagram", fromlist=["resolve_instagram_url"]).resolve_instagram_url(str(req.url))
    import hashlib
    request_id = hashlib.sha256(f"instagram-{resolved['media_id']}-{req.mode}".encode()).hexdigest()[:20]
    cached = extractor.cache.get(f"instagram-{resolved['media_id']}-{req.mode}") if not req.force_refresh else None
    if cached:
        RESULTS[request_id] = cached
        return ExtractionAccepted(id=request_id, status="complete", cached=True)
    RESULTS[request_id] = {"id": request_id, "status": "processing"}
    background.add_task(_run_extract, req)
    return ExtractionAccepted(id=request_id, status="queued", cached=False)


@app.post("/v1/extractions/sync", response_model=ExtractionResult, dependencies=[Depends(require_api_key)])
async def create_extraction_sync(req: ExtractionRequest):
    result = await extractor.extract(str(req.url), req.mode, req.force_refresh)
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
