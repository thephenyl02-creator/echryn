import pytest

from app.services.speech import (
    _speech_chunk_seconds,
    _total_speech_seconds,
    native_audio_policy,
    speech_analyze,
)


def test_licensed_music_without_original_sound_still_requires_vad():
    native = {
        "music": {"audio_cluster_id": "177258346273870"},
        "original_sound_info": None,
    }

    policy = native_audio_policy(native)

    assert policy["action"] == "inspect_audio"
    assert policy["reason"] == "licensed_music_requires_vad"
    assert policy["licensed_music"] is True


def test_original_sound_signal_keeps_speech_check(monkeypatch):
    native = {
        "music": {"audio_cluster_id": "music"},
        "original_sound_info": {"audio_asset_id": "voice"},
    }

    policy = native_audio_policy(native)

    assert policy["action"] == "inspect_audio"
    assert policy["original_sound_signal"] is True


def test_no_music_keeps_speech_check(monkeypatch):
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


@pytest.mark.asyncio
async def test_speech_analyze_runs_vad_for_licensed_music(tmp_path, monkeypatch):
    from app.services import speech

    monkeypatch.setattr(speech.settings, "echryn_min_total_speech_seconds", 0.6)
    monkeypatch.setattr(
        speech,
        "_vad_sync",
        lambda _: {
            "duration_seconds": 10.0,
            "speech_seconds": 0.0,
            "speech_ratio": 0.0,
            "chunks": [],
            "chunks_seconds": [],
        },
    )

    result = await speech_analyze(
        tmp_path / "dummy.mp4",
        {
            "music": {"audio_cluster_id": "licensed"},
            "original_sound_info": None,
        },
    )

    assert result["status"] == "no_speech_detected"
    assert result["source"] == "silero_vad"
    assert result["policy"]["reason"] == "licensed_music_requires_vad"


@pytest.mark.asyncio
async def test_speech_analyze_stops_before_whisper_when_vad_finds_no_speech(tmp_path, monkeypatch):
    from app.services import speech

    monkeypatch.setattr(speech.settings, "echryn_min_total_speech_seconds", 0.6)
    monkeypatch.setattr(
        speech,
        "_vad_sync",
        lambda _: {
            "duration_seconds": 10.0,
            "speech_seconds": 0.0,
            "speech_ratio": 0.0,
            "chunks": [],
            "chunks_seconds": [],
        },
    )

    def should_not_transcribe(_):
        raise AssertionError("Whisper should not run when VAD finds no speech")

    monkeypatch.setattr(speech, "_transcribe_sync", should_not_transcribe)

    result = await speech_analyze(
        tmp_path / "dummy.mp4",
        {"music": {}, "original_sound_info": None},
    )

    assert result["status"] == "no_speech_detected"
    assert result["source"] == "silero_vad"


@pytest.mark.asyncio
async def test_speech_analyze_transcribes_when_vad_finds_speech(tmp_path, monkeypatch):
    from app.services import speech

    monkeypatch.setattr(speech.settings, "echryn_min_total_speech_seconds", 0.6)
    monkeypatch.setattr(
        speech,
        "_vad_sync",
        lambda _: {
            "duration_seconds": 10.0,
            "speech_seconds": 2.0,
            "speech_ratio": 0.2,
            "chunks": [{"start": 16000, "end": 48000}],
            "chunks_seconds": [{"start": 1.0, "end": 3.0}],
        },
    )
    monkeypatch.setattr(
        speech,
        "_transcribe_sync",
        lambda _: {
            "text": "This is useful speech.",
            "language": "en",
            "language_probability": 0.99,
            "segments": [
                {
                    "start": 1.0,
                    "end": 3.0,
                    "text": "This is useful speech.",
                    "average_log_probability": -0.1,
                    "no_speech_probability": 0.01,
                    "words": [],
                }
            ],
        },
    )

    result = await speech_analyze(
        tmp_path / "dummy.mp4",
        {"music": {}, "original_sound_info": None},
    )

    assert result["status"] == "available"
    assert result["source"] == "faster_whisper"
    assert result["value"]["text"] == "This is useful speech."
