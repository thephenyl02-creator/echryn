from typing import Any

GENERIC_HINTS = {
    "comment", "link in bio", "follow", "share", "save", "dm", "repost",
}


def substantive_text(value: Any) -> bool:
    if not isinstance(value, str):
        return bool(value)
    text = " ".join(value.split()).strip()
    if len(text) < 24:
        return False
    lower = text.lower()
    words = [w for w in lower.split() if w.isalpha()]
    if not words:
        return False
    generic_hits = sum(1 for hint in GENERIC_HINTS if hint in lower)
    return len(words) >= 6 and generic_hits <= 2


def semantic_coverage(native: dict[str, Any]) -> dict[str, Any]:
    candidates = {
        "caption": native.get("caption"),
        "overlay_info": native.get("overlay_info"),
        "reusable_text": native.get("reusable_text"),
        "accessibility_caption": native.get("accessibility_caption"),
    }
    substantive = [k for k, v in candidates.items() if substantive_text(v)]
    return {
        "covered": bool(substantive),
        "substantive_sources": substantive,
        "reason": "substantive_native_text" if substantive else "native_metadata_without_semantic_content",
    }
