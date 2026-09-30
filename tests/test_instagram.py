from app.adapters.instagram import resolve_instagram_url, shortcode_to_media_id


def test_shortcode_decode_known_target():
    assert shortcode_to_media_id("Dd10cOlujGD") == "3996330882590454147"


def test_resolver():
    out = resolve_instagram_url("https://www.instagram.com/reel/Dd10cOlujGD/?igsh=x")
    assert out["platform"] == "instagram"
    assert out["shortcode"] == "Dd10cOlujGD"
    assert out["media_id"] == "3996330882590454147"
