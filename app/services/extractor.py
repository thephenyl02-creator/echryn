import hashlib
from pathlib import Path
from typing import Any

from app.adapters.instagram import InstagramClient, normalize_native, resolve_instagram_url
from app.services.coverage import semantic_coverage
from app.services.media import download_media, extract_frames, local_visual_analyze, probe_media, speech_analyze, temp_workspace
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

            need_media = mode in {"deep", "evidence"} or (mode == "auto" and not coverage["covered"])

            if mode == "metadata":
                result["visual"] = {"status": "skipped_by_policy", "reason": "metadata mode"}
                result["speech"] = {"status": "skipped_by_policy", "reason": "metadata mode"}

            elif need_media and normalized["media"].get("video_url"):
                with temp_workspace("echryn-") as td:
                    root = Path(td)
                    media_path = root / "source.mp4"

                    dl = await download_media(normalized["media"]["video_url"], media_path)
                    probe = await probe_media(media_path)
                    frames = await extract_frames(media_path, root / "frames")

                    result["media"].update(
                        {
                            "downloaded_bytes": dl["bytes"],
                            "probe": probe,
                            "sampled_frames": len(frames),
                        }
                    )

                    result["visual"] = await local_visual_analyze(
                        frames,
                        include_inline_frames=(mode == "evidence"),
                    )
                    result["speech"] = await speech_analyze(media_path)

                    result["provenance"].append(
                        {
                            "source": "temporary_media",
                            "status": "available",
                            "deleted_after_processing": True,
                        }
                    )

                    if result["visual"].get("ocr", {}).get("status") == "available":
                        result["provenance"].append(
                            {
                                "source": "local_ocr",
                                "engine": "tesseract",
                                "status": "available",
                            }
                        )

                    if result["visual"].get("frames"):
                        result["provenance"].append(
                            {
                                "source": "compressed_frame_evidence",
                                "format": "webp",
                                "status": "available",
                            }
                        )

            elif need_media:
                result["visual"] = {
                    "status": "not_exposed",
                    "reason": "platform did not expose a downloadable video resource",
                }
                result["speech"] = {
                    "status": "not_exposed",
                    "reason": "platform did not expose a downloadable video resource",
                }

            else:
                result["visual"] = {
                    "status": "not_applicable",
                    "reason": "native semantic coverage sufficient",
                }
                result["speech"] = {
                    "status": "not_applicable",
                    "reason": "native semantic coverage sufficient",
                }

            summary_parts: list[str] = []
            if result["native"].get("caption"):
                summary_parts.append(result["native"]["caption"])

            ocr_text = result.get("visual", {}).get("ocr", {}).get("text")
            if ocr_text:
                summary_parts.append(ocr_text)

            speech_value = result.get("speech", {}).get("value")
            if result.get("speech", {}).get("status") == "available" and speech_value:
                if isinstance(speech_value, dict) and speech_value.get("text"):
                    summary_parts.append(str(speech_value["text"]))
                elif isinstance(speech_value, str):
                    summary_parts.append(speech_value)

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
