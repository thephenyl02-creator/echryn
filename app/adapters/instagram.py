import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import settings

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
SHORTCODE_RE = re.compile(r"/(?:reel|reels|p)/([A-Za-z0-9_-]+)")


def shortcode_to_media_id(shortcode: str) -> str:
    n = 0
    for ch in shortcode:
        idx = ALPHABET.find(ch)
        if idx < 0:
            raise ValueError(f"Invalid Instagram shortcode character: {ch}")
        n = n * 64 + idx
    return str(n)


def resolve_instagram_url(url: str) -> dict[str, str]:
    parsed = urlparse(url)
    host = parsed.netloc.lower().split(":")[0]
    if host not in {"instagram.com", "www.instagram.com", "m.instagram.com"}:
        raise ValueError("Only Instagram URLs are supported in v1")
    m = SHORTCODE_RE.search(parsed.path)
    if not m:
        raise ValueError("Unsupported Instagram URL; expected /reel/, /reels/, or /p/")
    shortcode = m.group(1)
    return {
        "platform": "instagram",
        "shortcode": shortcode,
        "media_id": shortcode_to_media_id(shortcode),
        "canonical_url": f"https://www.instagram.com/reel/{shortcode}/",
    }


@dataclass
class InstagramSession:
    sessionid: str
    csrftoken: str | None = None
    ds_user_id: str | None = None

    @classmethod
    def from_settings(cls) -> "InstagramSession | None":
        sessionid = (settings.instagram_sessionid or "").strip()
        if not sessionid:
            return None
        csrftoken = (settings.instagram_csrftoken or "").strip() or None
        ds_user_id = (settings.instagram_ds_user_id or "").strip() or None
        return cls(
            sessionid=sessionid,
            csrftoken=csrftoken,
            ds_user_id=ds_user_id,
        )

    def cookies(self) -> dict[str, str]:
        out = {"sessionid": self.sessionid.strip()}
        if self.csrftoken:
            out["csrftoken"] = self.csrftoken.strip()
        if self.ds_user_id:
            out["ds_user_id"] = self.ds_user_id.strip()
        return out


class InstagramClient:
    def __init__(self, session: InstagramSession | None = None):
        self.session = session or InstagramSession.from_settings()

    async def media_info(self, media_id: str) -> dict[str, Any]:
        if not self.session:
            raise RuntimeError("Instagram authenticated session is not configured")
        headers = {
            "User-Agent": settings.instagram_user_agent,
            "Accept": "*/*",
            "X-IG-App-ID": "936619743392459",
            "Referer": "https://www.instagram.com/",
        }
        if self.session.csrftoken:
            headers["X-CSRFToken"] = self.session.csrftoken
        url = f"https://www.instagram.com/api/v1/media/{media_id}/info/"
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=headers, cookies=self.session.cookies()) as client:
            r = await client.get(url)
            if r.status_code in {401, 403}:
                raise RuntimeError("NEEDS_MANUAL_AUTH")
            if r.status_code == 429:
                raise RuntimeError("RATE_LIMITED")
            r.raise_for_status()
            return r.json()


def pick_best_video_url(item: dict[str, Any]) -> str | None:
    versions = item.get("video_versions") or []
    if versions:
        best = max(versions, key=lambda x: (x.get("width", 0) * x.get("height", 0), x.get("bitrate", 0) or 0))
        return best.get("url")
    return None



def extract_carousel_images(item: dict[str, Any]) -> dict[str, Any]:
    children = item.get("carousel_media") or []
    if str(item.get("media_type")) != "8" and not children:
        return {"is_carousel": False, "slide_count": 0, "images": []}
    count = max(len(children), int(item.get("carousel_media_count") or 0))
    images = []
    for i in range(count):
        child = children[i] if i < len(children) and isinstance(children[i], dict) else {}
        candidates = (child.get("image_versions2") or {}).get("candidates") or []
        candidates = [v for v in candidates if isinstance(v, dict) and
                      isinstance(v.get("url"), str) and v["url"].startswith("https://")]
        best = max(candidates, key=lambda v: (int(v.get("width") or 0)*int(v.get("height") or 0),
                                               int(v.get("width") or 0)), default={})
        images.append({
            "slide_index": i+1,
            "kind": "video_thumbnail" if str(child.get("media_type")) == "2" else "image",
            "url": best.get("url"),
            "width": best.get("width"),
            "height": best.get("height"),
            "accessibility_caption": child.get("accessibility_caption"),
        })
    return {"is_carousel": True, "slide_count": count, "images": images}


def normalize_native(raw: dict[str, Any]) -> dict[str, Any]:
    items = raw.get("items") or []
    if not items:
        raise RuntimeError("Instagram returned no media item")
    item = items[0]
    user = item.get("user") or {}
    caption_obj = item.get("caption") or {}
    music = item.get("music_metadata") or item.get("clips_metadata", {}).get("music_info") or {}
    overlay = item.get("media_overlay_info")
    reusable = item.get("reusable_text_info") or item.get("reusable_text_attribute_string")
    accessibility = item.get("accessibility_caption")
    original_sound = item.get("original_sound_info")
    video_url = pick_best_video_url(item)
    return {
        "item": item,
        "author": {
            "id": user.get("pk") or user.get("id"),
            "username": user.get("username"),
            "full_name": user.get("full_name"),
            "verified": user.get("is_verified"),
        },
        "native": {
            "caption": caption_obj.get("text") if isinstance(caption_obj, dict) else None,
            "like_count": item.get("like_count"),
            "comment_count": item.get("comment_count"),
            "play_count": item.get("play_count"),
            "duration_seconds": item.get("video_duration"),
            "overlay_info": overlay,
            "reusable_text": reusable,
            "accessibility_caption": accessibility,
            "original_sound_info": original_sound,
            "music": music,
            "is_ai_generated": item.get("is_ai_generated"),
        },
        "media": {
            "video_url": video_url,
            "carousel": extract_carousel_images(item),
            "image_versions2": item.get("image_versions2"),
            "dash_info": item.get("video_dash_manifest") or item.get("dash_info"),
        },
    }
