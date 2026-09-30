from app.services.speech import (
    _speech_chunk_seconds,
    _total_speech_seconds,
    native_audio_policy,
)


def test_licensed_music_without_original_sound_skips_transcription(monkeypatch):
    from app.services import speech

    monkeypatch.setattr(speech.settings, "echryn_skip_licensed_music", True)
    native = {
        "music": {"audio_cluster_id": "177258346273870"},
        "original_sound_info": None,
    }

    policy = native_audio_policy(native)

    assert policy["action"] == "skip_transcription"
    assert policy["reason"] == "licensed_music_without_original_sound_signal"
    assert policy["licensed_music"] is True


def test_original_sound_signal_keeps_speech_check(monkeypatch):
    from app.services import speech

    monkeypatch.setattr(speech.settings, "echryn_skip_licensed_music", True)
    native = {
        "music": {"audio_cluster_id": "music"},
        "original_sound_info": {"audio_asset_id": "voice"},
    }

    policy = native_audio_policy(native)

    assert policy["action"] == "inspect_audio"
    assert policy["original_sound_signal"] is True


def test_no_music_keeps_speech_check(monkeypatch):
    from app.services import speech

    monkeypatch.setattr(speech.settings, "echryn_skip_licensed_music", True)
    policy = native_audio_policy({"music": {}, "original_sound_info": None})

    assert policy["action"] == "inspect_audio"


def test_speech_chunk_helpers_use_16khz_samples():
    chunks = [
        {"start": 0, "end": 8000},
        {"start": 16000, "end": 32000},
    ]

    assert _total_speech_seconds(chunks) == 1.5
    assert _speech_chunk_seconds(chunks) == [
        {"start": 0.0, "end": 0.5},
        {"start": 1.0, "end": 2.0},
    ]
