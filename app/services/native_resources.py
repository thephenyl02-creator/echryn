import html
import re
from typing import Any

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

    for path, _, value in _walk(item):
        if not _TEXT_KEY_RE.search(path):
            continue

        if isinstance(value, str) and value.startswith(("http://", "https://")):
            if value not in seen:
                seen.add(value)
                tracks.append({"path": path, "url": html.unescape(value)})
        elif isinstance(value, dict):
            for field in ("url", "src", "uri"):
                url = value.get(field)
                if isinstance(url, str) and url.startswith(("http://", "https://")) and url not in seen:
                    seen.add(url)
                    tracks.append(
                        {
                            "path": f"{path}.{field}",
                            "url": html.unescape(url),
                            "language": value.get("language") or value.get("lang"),
                            "mime_type": value.get("mime_type") or value.get("mimeType"),
                        }
                    )

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
    for match in _URL_RE.findall(decoded):
        url = match.rstrip(",'\"<>")
        if url and url not in urls:
            urls.append(url)

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
