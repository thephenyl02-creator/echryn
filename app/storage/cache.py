import json
import time
from pathlib import Path
from typing import Any

from app.config import settings


class FileCache:
    def __init__(self):
        self.root = settings.data_dir / "cache"
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe = "".join(ch for ch in key if ch.isalnum() or ch in "-_")
        return self.root / f"{safe}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        p = self._path(key)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text())
            if time.time() - data.get("_cached_at", 0) > settings.echryn_cache_ttl_seconds:
                return None
            return data.get("result")
        except Exception:
            return None

    def put(self, key: str, result: dict[str, Any]) -> None:
        p = self._path(key)
        p.write_text(json.dumps({"_cached_at": time.time(), "result": result}, ensure_ascii=False))
