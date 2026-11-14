"""Globally shared V1 admission gate stored in private GCS with generation CAS.

A single active extraction (with a lease longer than Cloud Run's request timeout),
10 admissions per rolling hour and 50 per UTC day. Unavailable storage fails closed.
"""
import asyncio
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from app.config import settings

LOG = logging.getLogger(__name__)
OBJECT_KEY = "control/v1_global_admissions.json"


class V1GateError(RuntimeError):
    def __init__(self, code: str, status_code: int = 429, retry_after: int = 60):
        self.code = code
        self.status_code = status_code
        self.retry_after = retry_after
        super().__init__(code)


def _blob():
    if not settings.echryn_frame_bucket:
        raise V1GateError("limiter_storage_unconfigured", 503, 30)
    from google.cloud import storage
    return storage.Client().bucket(settings.echryn_frame_bucket).blob(OBJECT_KEY)


def _read(blob):
    from google.api_core.exceptions import NotFound
    try:
        blob.reload(timeout=12)
    except NotFound:
        return {}, 0
    generation = int(blob.generation)
    try:
        data = blob.download_as_bytes(if_generation_match=generation, timeout=12)
    except NotFound:
        return {}, 0
    return json.loads(data), generation


def _write(blob, state, generation):
    blob.upload_from_string(
        json.dumps(state, separators=(",", ":")),
        content_type="application/json",
        if_generation_match=generation,
        timeout=12,
    )


def _claim():
    from google.api_core.exceptions import PreconditionFailed
    try:
        blob = _blob()
    except V1GateError:
        raise
    except Exception as exc:
        LOG.exception("V1 admission storage initialization failed")
        raise V1GateError("limiter_unavailable", 503, 30) from exc
    token = uuid.uuid4().hex
    for attempt in range(12):
        now = time.time()
        try:
            state, generation = _read(blob)
            day = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")
            hourly = [x for x in state.get("hourly", []) if now - 3600 < x <= now]
            daily = int(state.get("daily", 0)) if state.get("day") == day else 0
            active = state.get("active") or {}
            if float(active.get("until", 0)) > now:
                raise V1GateError("v1_extraction_busy", 429, min(360, max(1, int(active["until"] - now))))
            if daily >= settings.echryn_v1_daily_limit:
                raise V1GateError("v1_daily_limit_reached", 429, 3600)
            if len(hourly) >= settings.echryn_v1_hourly_limit:
                raise V1GateError("v1_hourly_limit_reached", 429, max(1, int(hourly[0] + 3600 - now)))
            state = {
                "day": day, "daily": daily + 1,
                "hourly": hourly + [now],
                "active": {"token": token, "until": now + settings.echryn_v1_lease_seconds},
            }
            _write(blob, state, generation)
            return token
        except PreconditionFailed:
            continue
        except V1GateError:
            raise
        except Exception as exc:
            LOG.exception("V1 admission storage failed")
            raise V1GateError("limiter_unavailable", 503, 30) from exc
    raise V1GateError("limiter_contention", 503, 5)


def _release(token: str):
    from google.api_core.exceptions import PreconditionFailed
    blob = _blob()
    for attempt in range(12):
        try:
            state, generation = _read(blob)
            if (state.get("active") or {}).get("token") != token:
                return
            state["active"] = None
            _write(blob, state, generation)
            return
        except PreconditionFailed:
            continue
    LOG.error("Could not release global extraction lease after CAS contention")


@asynccontextmanager
async def extraction_gate():
    if not settings.echryn_public_enabled:
        raise V1GateError("echryn_temporarily_disabled", 503, 60)
    if not settings.echryn_v1_limits_enabled:
        if os.getenv("K_SERVICE"):
            raise V1GateError("public_limits_required", 503, 30)
        yield
        return
    token = await asyncio.to_thread(_claim)
    try:
        yield
    finally:
        try:
            await asyncio.to_thread(_release, token)
        except Exception:
            LOG.exception("Lease release failed; lease automatically expires")
