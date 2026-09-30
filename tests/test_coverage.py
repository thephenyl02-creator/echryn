from app.services.coverage import semantic_coverage


def test_generic_caption_is_not_semantic_coverage():
    native = {"caption": "Comment REINVENT for access #startup #college #entrepreneur"}
    assert semantic_coverage(native)["covered"] is False


def test_substantive_caption_is_coverage():
    native = {"caption": "This video explains how abandoned patents can be searched, summarized, reinvented with AI, and compared against competitors."}
    assert semantic_coverage(native)["covered"] is True
