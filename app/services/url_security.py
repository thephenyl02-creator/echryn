"""Allowlist remote hosts before fetching untrusted Instagram metadata URLs."""
from urllib.parse import urlsplit


def trusted_instagram_media_url(url: str) -> bool:
    try:
        u = urlsplit(url)
        host = (u.hostname or "").lower()
        return (u.scheme == "https" and u.username is None and
                u.password is None and u.port in (None, 443) and
                any(host == base or host.endswith("." + base)
                    for base in ("cdninstagram.com", "fbcdn.net")))
    except (TypeError, ValueError, AttributeError):
        return False


def trusted_text_track_url(url: str) -> bool:
    if trusted_instagram_media_url(url):
        return True
    try:
        u = urlsplit(url)
        return (u.scheme == "https" and u.username is None and
                u.password is None and u.port in (None, 443) and
                (u.hostname or "").lower() in {"instagram.com", "www.instagram.com"})
    except (TypeError, ValueError, AttributeError):
        return False
