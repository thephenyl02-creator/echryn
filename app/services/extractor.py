import hashlib
from pathlib import Path
from typing import Any

from app.adapters.instagram import InstagramClient, normalize_native, resolve_instagram_url
from app.services.coverage import semantic_coverage
from app.services.media import download_media, extract_frames, probe_media, speech_analyze, temp_workspace, vision_analyze
from app.storage.cache import FileCache


class Extractor:
    def __init__(self):
        self.cache = FileCache()
        self.instagram = InstagramClient()

    async def extract(self, url: str, mode: str = "auto", force_refresh: bool = False) -> dict[str, Any]:
        resolved = resolve_instagram_url(url)
        cache_key = f"instagram-{resolved['media_id']}-{mode}"
        request_id = hashlib.sha256(cache_key.encode()).hexdigest()[:20]

        if not force_refresh:
            cached = self.cache.get(cache_key)
            if cached:
                cached.setdefault("diagnostics", {})["cached"] = True
                return cached

        result: dict[str, Any] = {
            "id": request_id,
            "status": "complete",
            "source": resolved,
            "author": {},
            "native": {},
            "visual": {"status": "not_applicable"},
            "speech": {"status": "not_applicable"},
            "media": {},
            "summary": {},
            "provenance": [],
            "diagnostics": {"mode": mode, "cached": False},
        }

        try:
            raw = await self.instagram.media_info(resolved["media_id"])
            normalized = normalize_native(raw)
            result["author"] = normalized["author"]
            result["native"] = normalized["native"]
            result["media"] = {k: v for k, v in normalized["media"].items() if k != "video_url"}
            result["provenance"].append({"source": "instagram_media_info", "status": "available"})
            coverage = semantic_coverage(result["native"])
            result["diagnostics"]["semantic_coverage"] = coverage

            need_deep = mode == "deep" or (mode == "auto" and not coverage["covered"])
            if mode == "metadata":
                result["visual"] = {"status": "skipped_by_policy", "reason": "metadata mode"}
                result["speech"] = {"status": "skipped_by_policy", "reason": "metadata mode"}
            elif need_deep and normalized["media"].get("video_url"):
                with temp_workspace("echryn-") as td:
                    root = Path(td)
                    media_path = root / "source.mp4"
                    dl = await download_media(normalized["media"]["video_url"], media_path)
                    probe = await probe_media(media_path)
                    frames = await extract_frames(media_path, root / "frames")
                    result["media"].update({"downloaded_bytes": dl["bytes"], "probe": probe, "sampled_frames": len(frames)})
                    result["visual"] = await vision_analyze(frames)
                    # Speech remains conditional at provider level. In v1, only called after deep fallback.
                    result["speech"] = await speech_analyze(media_path)
                    result["provenance"].append({"source": "temporary_media", "status": "available", "deleted_after_processing": True})
            else:
                result["visual"] = {"status": "not_applicable", "reason": "native semantic coverage sufficient"}
                result["speech"] = {"status": "not_applicable", "reason": "native semantic coverage sufficient"}

            summary_parts = []
            if result["native"].get("caption"):
                summary_parts.append(result["native"]["caption"])
            v = result.get("visual", {})
            if v.get("status") == "available":
                summary_parts.append("Visual analysis available in result.visual")
            s = result.get("speech", {})
            if s.get("status") == "available":
                summary_parts.append("Speech transcript available in result.speech")
            result["summary"] = {
                "text": "\n\n".join(summary_parts) if summary_parts else "No substantive text summary available.",
                "semantic_coverage": coverage,
            }

            self.cache.put(cache_key, result)
            return result
        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)
            result["diagnostics"]["exception_type"] = e.__class__.__name__
            return result
