import hashlib
from pathlib import Path
from typing import Any

from app.adapters.instagram import InstagramClient, normalize_native, resolve_instagram_url
from app.services.coverage import semantic_coverage
from app.services.media import download_media, extract_frames, local_visual_analyze, probe_media, temp_workspace
from app.services.native_resources import inspect_native_resources
from app.services.speech import speech_analyze
from app.storage.cache import FileCache


class Extractor:
    def __init__(self):
        self.cache = FileCache()
        self.instagram = InstagramClient()

    async def extract(
        self,
        url: str,
        mode: str = "auto",
        multimodal: bool = False,
        frame_delivery: str = "urls",
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        resolved = resolve_instagram_url(url)
        cache_key = (
            f"instagram-{resolved['media_id']}-{mode}"
            f"-mm{int(multimodal)}-fd{frame_delivery}"
        )
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
            "diagnostics": {
                "mode": mode,
                "multimodal": multimodal,
                "frame_delivery": frame_delivery,
                "cached": False,
            },
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

            native_resources = inspect_native_resources(
                normalized["item"],
                normalized["media"],
            )
            result["media"]["native_resources"] = native_resources
            result["provenance"].append(
                {
                    "source": "instagram_native_resources",
                    "status": native_resources["status"],
                    "reason": native_resources["reason"],
                }
            )

            native_resource_covered = native_resources.get("semantic_coverage", False)
            need_media = (
                mode in {"deep", "evidence"}
                or (
                    mode == "auto"
                    and not coverage["covered"]
                    and not native_resource_covered
                )
            )

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

                    visual_delivery = frame_delivery if (multimodal or mode == "evidence") else "none"
                    result["visual"] = await local_visual_analyze(
                        frames,
                        frame_delivery=visual_delivery,
                        extraction_id=request_id,
                        run_ocr=not multimodal,
                    )

                    has_audio_stream = any(
                        stream.get("codec_type") == "audio"
                        for stream in probe.get("streams", [])
                    )
                    if has_audio_stream:
                        result["speech"] = await speech_analyze(media_path, result["native"])
                    else:
                        result["speech"] = {
                            "status": "not_applicable",
                            "source": "media_probe",
                            "reason": "no_audio_stream",
                        }

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

                    speech = result.get("speech", {})
                    detector = speech.get("detector", {})
                    if detector.get("engine") == "silero_vad":
                        result["provenance"].append(
                            {
                                "source": "local_speech_detection",
                                "engine": "silero_vad",
                                "status": detector.get("status", "available"),
                            }
                        )
                    if speech.get("source") == "faster_whisper" and speech.get("status") == "available":
                        result["provenance"].append(
                            {
                                "source": "local_speech_transcription",
                                "engine": "faster_whisper",
                                "model": speech.get("model", {}).get("model"),
                                "status": "available",
                            }
                        )
                    if speech.get("source") == "native_audio_policy":
                        result["provenance"].append(
                            {
                                "source": "native_audio_policy",
                                "status": speech.get("status"),
                                "reason": speech.get("reason"),
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

            for entry in result.get("media", {}).get("native_resources", {}).get("semantic_text", []):
                text = entry.get("text")
                if text and text not in summary_parts:
                    summary_parts.append(text)

            ocr_payload = result.get("visual", {}).get("ocr", {})
            ocr_text = ocr_payload.get("prominent_text") or ocr_payload.get("text")
            if ocr_text:
                summary_parts.append(ocr_text)
            elif multimodal and result.get("visual", {}).get("frames"):
                summary_parts.append("Visual frame evidence available for multimodal interpretation.")

            speech_value = result.get("speech", {}).get("value")
            if result.get("speech", {}).get("status") == "available" and speech_value:
                if isinstance(speech_value, dict) and speech_value.get("text"):
                    summary_parts.append(str(speech_value["text"]))
                elif isinstance(speech_value, str):
                    summary_parts.append(speech_value)

            effective_coverage = dict(coverage)
            if native_resource_covered and not effective_coverage.get("covered"):
                effective_coverage = {
                    "covered": True,
                    "substantive_sources": ["native_resource_text"],
                    "reason": "substantive_native_resource_text",
                }

            result["summary"] = {
                "text": "\n\n".join(summary_parts) if summary_parts else "No substantive text summary available.",
                "semantic_coverage": effective_coverage,
            }

            self.cache.put(cache_key, result)
            return result

        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)
            result["diagnostics"]["exception_type"] = e.__class__.__name__
            return result
