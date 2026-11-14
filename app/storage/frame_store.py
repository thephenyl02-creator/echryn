"""Private, shared Cloud Storage for temporary signed frame URLs."""
from functools import lru_cache
from pathlib import Path

from app.config import settings


@lru_cache(maxsize=1)
def _bucket():
    if not settings.echryn_frame_bucket:
        return None
    from google.cloud import storage
    return storage.Client().bucket(settings.echryn_frame_bucket)


def _object_key(extraction_id: str, filename: str) -> str:
    return f"frames/{extraction_id}/{filename}"


def upload_frame(path: Path, extraction_id: str, filename: str, mime: str) -> None:
    bucket = _bucket()
    if bucket is None:
        return
    bucket.blob(_object_key(extraction_id, filename)).upload_from_filename(
        str(path), content_type=mime, timeout=30,
    )


def fetch_frame(extraction_id: str, filename: str) -> bytes | None:
    bucket = _bucket()
    if bucket is None:
        return None
    from google.api_core.exceptions import NotFound
    try:
        return bucket.blob(_object_key(extraction_id, filename)).download_as_bytes(
            timeout=30,
        )
    except NotFound:
        return None


def frame_exists(extraction_id: str, filename: str) -> bool:
    bucket = _bucket()
    if bucket is None:
        return False
    return bucket.blob(_object_key(extraction_id, filename)).exists(timeout=15)
