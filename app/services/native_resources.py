import html
import re
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

    for path, key, value in _walk(item):
        # Only treat the current field as text-bearing. Do not inherit a
        # "caption" match from an ancestor such as caption.user.profile_pic_url.
        if not _TEXT_KEY_RE.search(key):
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
