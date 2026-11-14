from app.services.coverage import semantic_coverage


def test_generic_caption_is_not_semantic_coverage():
    native = {"caption": "Comment REINVENT for access #startup #college #entrepreneur"}
    assert semantic_coverage(native)["covered"] is False


def test_substantive_caption_is_coverage():
    native = {"caption": "This video explains how abandoned patents can be searched, summarized, reinvented with AI, and compared against competitors."}
    assert semantic_coverage(native)["covered"] is True
from app.services.coverage import substantive_text


def test_reel_promotional_title_is_not_semantic_coverage():
    assert not semantic_coverage({"caption": "The Open-Source AI Game Engine You Can Play Today"})["covered"]
    assert not substantive_text({"title": "The Most Amazing Free AI Game Engine You Can Play Today"})


def test_nontext_metadata_does_not_count_as_caption():
    assert not semantic_coverage({"overlay_info": {"id": 123, "type": "music", "url": "https://example.com"}})["covered"]


def test_structured_actual_text_can_count_as_semantic_coverage():
    text = ("This tutorial explains how to search abandoned patents, "
            "review their summaries, and compare competing products.")
    assert substantive_text({"text": text})
    assert semantic_coverage({"overlay_info": {"text": text}})["covered"]
