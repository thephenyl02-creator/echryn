from app.services.native_resources import inspect_native_resources


def test_native_resource_text_can_satisfy_semantic_coverage():
    item = {
        "clips_metadata": {
            "subtitle_info": {
                "text": (
                    "This tutorial explains how to search abandoned patents, "
                    "review their summaries, and compare competing products."
                )
            }
        }
    }
    result = inspect_native_resources(item, {"dash_info": None})

    assert result["status"] == "available"
    assert result["semantic_coverage"] is True
    assert result["reason"] == "substantive_native_resource_text"
    assert result["semantic_text"][0]["path"].endswith("subtitle_info")


def test_native_text_track_url_is_discovered():
    item = {
        "caption_tracks": [
            {
                "url": "https://cdn.example.com/en.vtt",
                "language": "en",
                "mime_type": "text/vtt",
            }
        ]
    }
    result = inspect_native_resources(item, {"dash_info": None})

    assert result["status"] == "available"
    assert result["semantic_coverage"] is False
    assert result["reason"] == "native_text_track_exposed"
    assert result["text_tracks"][0]["url"] == "https://cdn.example.com/en.vtt"


def test_dash_resources_are_exposed_without_claiming_semantics():
    media = {
        "dash_info": (
            "https://cdn.example.com/video.mp4 "
            "https://cdn.example.com/audio.mp4"
        )
    }
    result = inspect_native_resources({}, media)

    assert result["status"] == "absent"
    assert result["semantic_coverage"] is False
    assert result["dash"]["status"] == "available"
    assert result["dash"]["resource_count"] == 2
    assert result["dash"]["text_track_signal"] is False


def test_dash_text_signal_is_detected():
    media = {
        "dash_info": (
            '<AdaptationSet mimeType="text/vtt">'
            '<Representation codecs="wvtt" />'
            "</AdaptationSet>"
        )
    }
    result = inspect_native_resources({}, media)

    assert result["status"] == "available"
    assert result["reason"] == "native_text_track_exposed"
    assert result["dash"]["text_track_signal"] is True
