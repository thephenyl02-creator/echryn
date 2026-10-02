from app.services.native_resources import _text_from_track_payload, inspect_native_resources


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


def test_webvtt_payload_becomes_plain_text():
    payload = """WEBVTT

1
00:00:00.000 --> 00:00:02.000
Abandoned patents can be useful starting points.

2
00:00:02.000 --> 00:00:05.000
You can review them and compare competitors.
"""

    text = _text_from_track_payload(payload)

    assert text == (
        "Abandoned patents can be useful starting points. "
        "You can review them and compare competitors."
    )


def test_ttml_payload_becomes_plain_text():
    payload = (
        "<tt><body><div>"
        "<p begin='0s' end='2s'>This is a native subtitle sentence.</p>"
        "<p begin='2s' end='4s'>It explains the actual content.</p>"
        "</div></body></tt>"
    )

    text = _text_from_track_payload(payload)

    assert "This is a native subtitle sentence." in text
    assert "It explains the actual content." in text


def test_nested_caption_profile_picture_is_not_a_text_track():
    item = {
        "caption": {
            "text": "Comment REINVENT for access",
            "user": {
                "profile_pic_url": "https://cdn.example.com/avatar.jpg"
            },
        }
    }

    result = inspect_native_resources(item, {"dash_info": None})

    assert result["text_tracks"] == []
    assert result["semantic_coverage"] is False


def test_caption_track_container_preserves_metadata():
    item = {
        "caption_tracks": [
            {
                "url": "https://cdn.example.com/en.vtt",
                "language": "en",
                "mime_type": "text/vtt",
            },
            {
                "url": "https://cdn.example.com/es.vtt",
                "language": "es",
                "mime_type": "text/vtt",
            },
        ]
    }

    result = inspect_native_resources(item, {"dash_info": None})

    assert result["status"] == "available"
    assert result["reason"] == "native_text_track_exposed"
    assert [track["language"] for track in result["text_tracks"]] == ["en", "es"]
    assert all(track["mime_type"] == "text/vtt" for track in result["text_tracks"])
    assert result["text_tracks"][0]["path"] == "caption_tracks[0].url"


def test_caption_ancestor_does_not_turn_nested_image_into_text_track():
    item = {
        "caption": {
            "text": "Comment for access",
            "user": {
                "profile_pic_url": "https://cdn.example.com/avatar.jpg",
            },
        }
    }

    result = inspect_native_resources(item, {"dash_info": None})

    assert result["text_tracks"] == []


def test_dash_resource_urls_ignore_xml_namespace():
    media = {
        "dash_info": (
            '<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            '<Period><AdaptationSet>'
            '<Representation><BaseURL>'
            'https://cdn.example.com/video.mp4?x=1&amp;y=2'
            '</BaseURL></Representation>'
            '<Representation><BaseURL>'
            'https://cdn.example.com/audio.mp4'
            '</BaseURL></Representation>'
            '</AdaptationSet></Period></MPD>'
        )
    }

    result = inspect_native_resources({}, media)

    assert result["dash"]["resource_urls"] == [
        "https://cdn.example.com/video.mp4?x=1&y=2",
        "https://cdn.example.com/audio.mp4",
    ]
    assert result["dash"]["resource_count"] == 2
