import html
import re
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from app.services.coverage import substantive_text

_TEXT_KEY_RE = re.compile(
    r"(subtitle|caption|transcript|timed[_-]?text|text[_-]?track|closed[_-]?caption)",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://.*?(?=https?://|\s|$)", re.IGNORECASE)


def _walk(value: Any, path: str = ""):
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            yield child_path, str(key), child
            yield from _walk(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            yield child_path, str(index), child
            yield from _walk(child, child_path)


def _clean_text(value: str) -> str:
    return " ".join(html.unescape(value).split()).strip()


def _extract_text_candidates(item: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    for path, key, value in _walk(item):
        if not _TEXT_KEY_RE.search(key):
            continue

        values: list[str] = []
        if isinstance(value, str):
            values = [value]
        elif isinstance(value, dict):
            for field in ("text", "caption", "subtitle", "transcript", "value"):
                candidate = value.get(field)
                if isinstance(candidate, str):
                    values.append(candidate)

        for raw in values:
            cleaned = _clean_text(raw)
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            candidates.append(
                {
                    "path": path,
                    "text": cleaned,
                    "substantive": substantive_text(cleaned),
                }
            )

    return candidates


def _extract_text_track_urls(item: dict[str, Any]) -> list[dict[str, Any]]:
    tracks: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_track(path: str, value: Any, inherited: dict[str, Any] | None = None) -> None:
        metadata = inherited or {}

        if isinstance(value, str):
            if value.startswith(("http://", "https://")) and value not in seen:
                seen.add(value)
                tracks.append(
                    {
                        "path": path,
                        "url": html.unescape(value),
                        "language": metadata.get("language") or metadata.get("lang"),
                        "mime_type": metadata.get("mime_type") or metadata.get("mimeType"),
                    }
                )
            return

        if isinstance(value, dict):
            local_metadata = {
                "language": value.get("language") or value.get("lang") or metadata.get("language"),
                "mime_type": value.get("mime_type") or value.get("mimeType") or metadata.get("mime_type"),
            }
            for field in ("url", "src", "uri"):
                if field in value:
                    add_track(f"{path}.{field}", value[field], local_metadata)
            return

        if isinstance(value, list):
            for index, child in enumerate(value):
                add_track(f"{path}[{index}]", child, metadata)

    for path, key, value in _walk(item):
        # Match the current field itself. This allows real containers such as
        # "caption_tracks" while avoiding inherited matches from unrelated
        # descendants such as "caption.user.profile_pic_url".
        if _TEXT_KEY_RE.search(key):
            add_track(path, value)

    return tracks


def _inspect_dash(dash_info: Any) -> dict[str, Any]:
    if not isinstance(dash_info, str) or not dash_info.strip():
        return {
            "status": "absent",
            "resource_urls": [],
            "text_track_signal": False,
        }

    decoded = html.unescape(dash_info)
    urls: list[str] = []

    # Prefer actual DASH BaseURL elements. A generic URL regex also captures
    # XML namespace URLs and can overrun into closing tags.
    try:
        root = ET.fromstring(decoded)
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] != "BaseURL":
                continue
            value = (element.text or "").strip()
            if value.startswith(("http://", "https://")) and value not in urls:
                urls.append(value)
    except ET.ParseError:
        # Some Instagram responses are fragments rather than full MPDs. Fall
        # back to bounded BaseURL extraction rather than scanning every URL.
        for match in re.finditer(
            r"<BaseURL[^>]*>\s*(https?://.*?)\s*</BaseURL>",
            decoded,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            value = match.group(1).strip()
            if value not in urls:
                urls.append(value)

        # Backward-compatible fallback for simplified/plain resource lists.
        # Only use this when no BaseURL tags were found, and keep tokens bounded
        # to whitespace so XML namespace URLs are not swept up from real MPDs.
        if not urls and "<" not in decoded and ">" not in decoded:
            for token in decoded.split():
                if token.startswith(("http://", "https://")):
                    value = token.rstrip(",'\"")
                    if value not in urls:
                        urls.append(value)

    lower = decoded.lower()
    text_signal = any(
        token in lower
        for token in (
            "text/vtt",
            "application/ttml",
            "application/mp4; codecs=\"stpp",
            "wvtt",
            "stpp",
            "subtitle",
            "caption",
            "timedtext",
            "timed_text",
        )
    )

    return {
        "status": "available",
        "resource_urls": urls,
        "resource_count": len(urls),
        "text_track_signal": text_signal,
    }


def inspect_native_resources(
    item: dict[str, Any],
    media: dict[str, Any],
) -> dict[str, Any]:
    text_candidates = _extract_text_candidates(item)
    text_tracks = _extract_text_track_urls(item)
    dash = _inspect_dash(media.get("dash_info"))

    substantive = [entry for entry in text_candidates if entry["substantive"]]

    if substantive:
        status = "available"
        reason = "substantive_native_resource_text"
    elif text_tracks or dash.get("text_track_signal"):
        status = "available"
        reason = "native_text_track_exposed"
    else:
        status = "absent"
        reason = "no_substantive_native_text_resource"

    return {
        "status": status,
        "reason": reason,
        "semantic_text": substantive,
        "text_candidates": text_candidates,
        "text_tracks": text_tracks,
        "dash": dash,
        "semantic_coverage": bool(substantive),
    }


def _text_from_track_payload(payload: str) -> str:
    text = html.unescape(payload)
    text = re.sub(r"<[^>]+>", " ", text)
    lines: list[str] = []
    seen: set[str] = set()

    for raw in text.replace("\r", "\n").split("\n"):
        line = " ".join(raw.split()).strip()
        if not line:
            continue
        if line.upper() == "WEBVTT":
            continue
        if re.fullmatch(r"\d+", line):
            continue
        if "-->" in line:
            continue
        if line.startswith(("NOTE ", "STYLE", "REGION")):
            continue
        if line not in seen:
            seen.add(line)
            lines.append(line)

    return " ".join(lines).strip()


async def fetch_text_track_evidence(
    tracks: list[dict[str, Any]],
    *,
    user_agent: str,
    max_tracks: int = 3,
    max_bytes: int = 1_000_000,
) -> dict[str, Any]:
    if not tracks:
        return {
            "status": "not_applicable",
            "reason": "no_native_text_track_url",
            "tracks": [],
            "semantic_text": [],
            "semantic_coverage": False,
        }

    outputs: list[dict[str, Any]] = []
    semantic: list[dict[str, Any]] = []

    async with httpx.AsyncClient(
        timeout=15,
        follow_redirects=True,
        headers={"User-Agent": user_agent},
    ) as client:
        for track in tracks[:max_tracks]:
            url = track.get("url")
            if not isinstance(url, str):
                continue

            entry = {
                "url": url,
                "path": track.get("path"),
                "language": track.get("language"),
                "mime_type": track.get("mime_type"),
            }
            try:
                response = await client.get(url)
                response.raise_for_status()
                raw = response.content
                content_type = (response.headers.get("content-type") or "").lower()
                plausible_text = (
                    content_type.startswith("text/")
                    or "json" in content_type
                    or "xml" in content_type
                    or "vtt" in content_type
                    or "ttml" in content_type
                    or url.lower().split("?", 1)[0].endswith((".vtt", ".ttml", ".srt", ".xml", ".json"))
                )
                if not plausible_text:
                    entry.update(
                        {
                            "status": "failed",
                            "reason": "unsupported_text_track_content_type",
                            "content_type": content_type or None,
                        }
                    )
                    outputs.append(entry)
                    continue
                if len(raw) > max_bytes:
                    entry.update(
                        {
                            "status": "failed",
                            "reason": "text_track_exceeded_size_limit",
                            "bytes": len(raw),
                        }
                    )
                    outputs.append(entry)
                    continue

                decoded = raw.decode("utf-8", errors="replace")
                text = _text_from_track_payload(decoded)
                is_substantive = substantive_text(text)
                entry.update(
                    {
                        "status": "available",
                        "bytes": len(raw),
                        "text": text,
                        "substantive": is_substantive,
                    }
                )
                outputs.append(entry)

                if is_substantive:
                    semantic.append(
                        {
                            "source": "native_text_track",
                            "url": url,
                            "language": track.get("language"),
                            "text": text,
                        }
                    )
            except Exception as exc:
                entry.update(
                    {
                        "status": "failed",
                        "reason": "text_track_fetch_failed",
                        "error": str(exc),
                        "exception_type": exc.__class__.__name__,
                    }
                )
                outputs.append(entry)

    if semantic:
        status = "available"
        reason = "substantive_native_text_track"
    elif any(entry.get("status") == "available" for entry in outputs):
        status = "available"
        reason = "native_text_track_not_substantive"
    else:
        status = "failed"
        reason = "native_text_track_fetch_failed"

    return {
        "status": status,
        "reason": reason,
        "tracks": outputs,
        "semantic_text": semantic,
        "semantic_coverage": bool(semantic),
    }
