import json
import time
from pathlib import Path
from typing import Any

from app.config import settings


class FileCache:
    """Filesystem cache grouped by stable platform content identity.

    Each content identity owns one cache document. Request-specific presentation
    variants (mode, multimodal capability, frame delivery) live inside that
    document with independent TTL timestamps.
    """

    def __init__(self):
        self.root = settings.data_dir / "cache"
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, identity: str) -> Path:
        safe = "".join(ch for ch in identity if ch.isalnum() or ch in "-_")
        return self.root / f"{safe}.json"

    def _read_document(self, identity: str) -> dict[str, Any]:
        path = self._path(identity)
        if not path.exists():
            return {"identity": identity, "variants": {}}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("cache document is not an object")
            variants = data.get("variants")
            if not isinstance(variants, dict):
                variants = {}
            return {"identity": identity, "variants": variants}
        except Exception:
            return {"identity": identity, "variants": {}}

    def _write_document(self, identity: str, document: dict[str, Any]) -> None:
        path = self._path(identity)
        variants = document.get("variants") or {}
        if not variants:
            path.unlink(missing_ok=True)
            return
        path.write_text(
            json.dumps(
                {"identity": identity, "variants": variants},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def get_variant(self, identity: str, variant: str) -> dict[str, Any] | None:
        document = self._read_document(identity)
        variants = document["variants"]
        entry = variants.get(variant)
        if not isinstance(entry, dict):
            return None

        cached_at = entry.get("_cached_at", 0)
        if time.time() - cached_at > settings.echryn_cache_ttl_seconds:
            variants.pop(variant, None)
            self._write_document(identity, document)
            return None

        result = entry.get("result")
        return result if isinstance(result, dict) else None

    def put_variant(self, identity: str, variant: str, result: dict[str, Any]) -> None:
        document = self._read_document(identity)
        document["variants"][variant] = {
            "_cached_at": time.time(),
            "result": result,
        }
        self._write_document(identity, document)

    def delete_variant(self, identity: str, variant: str) -> None:
        document = self._read_document(identity)
        document["variants"].pop(variant, None)
        self._write_document(identity, document)
