import asyncio
import threading
from pathlib import Path
from typing import Any

from app.config import settings

_WHISPER_MODEL = None
_WHISPER_MODEL_KEY: tuple[str, str, str] | None = None
_WHISPER_MODEL_LOCK = threading.Lock()
_SAMPLE_RATE = 16000


def native_audio_policy(native: dict[str, Any]) -> dict[str, Any]:
    music = native.get("music")
    original_sound = native.get("original_sound_info")

    has_music = isinstance(music, dict) and bool(music)
    has_original_sound = isinstance(original_sound, dict) and bool(original_sound)

    # Licensed music metadata is only a hint. Reels can contain speech mixed over
    # licensed music, so native metadata alone is not enough to skip speech detection.
    return {
        "action": "inspect_audio",
        "reason": "licensed_music_requires_vad" if has_music else "speech_check_required",
        "licensed_music": has_music,
        "original_sound_signal": has_original_sound,
    }


def _speech_chunk_seconds(chunks: list[dict[str, int]]) -> list[dict[str, float]]:
    return [
        {
            "start": round(chunk["start"] / _SAMPLE_RATE, 3),
            "end": round(chunk["end"] / _SAMPLE_RATE, 3),
        }
        for chunk in chunks
        if chunk.get("end", 0) > chunk.get("start", 0)
    ]


def _total_speech_seconds(chunks: list[dict[str, int]]) -> float:
    samples = sum(max(0, chunk.get("end", 0) - chunk.get("start", 0)) for chunk in chunks)
    return samples / _SAMPLE_RATE


def _vad_sync(path: Path) -> dict[str, Any]:
    from faster_whisper.audio import decode_audio
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    audio = decode_audio(str(path), sampling_rate=_SAMPLE_RATE)
    duration_seconds = len(audio) / _SAMPLE_RATE if len(audio) else 0.0

    options = VadOptions(
        threshold=settings.echryn_vad_threshold,
        min_speech_duration_ms=settings.echryn_vad_min_speech_ms,
        min_silence_duration_ms=settings.echryn_vad_min_silence_ms,
        speech_pad_ms=settings.echryn_vad_speech_pad_ms,
    )
    chunks = get_speech_timestamps(audio, options, sampling_rate=_SAMPLE_RATE)
    speech_seconds = _total_speech_seconds(chunks)
    speech_ratio = speech_seconds / duration_seconds if duration_seconds > 0 else 0.0

    return {
        "duration_seconds": round(duration_seconds, 3),
        "speech_seconds": round(speech_seconds, 3),
        "speech_ratio": round(speech_ratio, 4),
        "chunks": chunks,
        "chunks_seconds": _speech_chunk_seconds(chunks),
    }


def _get_whisper_model():
    global _WHISPER_MODEL, _WHISPER_MODEL_KEY

    from faster_whisper import WhisperModel

    key = (
        settings.echryn_speech_model,
        settings.echryn_speech_device,
        settings.echryn_speech_compute_type,
    )

    with _WHISPER_MODEL_LOCK:
        if _WHISPER_MODEL is None or _WHISPER_MODEL_KEY != key:
            model_dir = settings.data_dir / "models"
            model_dir.mkdir(parents=True, exist_ok=True)
            _WHISPER_MODEL = WhisperModel(
                settings.echryn_speech_model,
                device=settings.echryn_speech_device,
                compute_type=settings.echryn_speech_compute_type,
                download_root=str(model_dir),
            )
            _WHISPER_MODEL_KEY = key

    return _WHISPER_MODEL


def _transcribe_sync(path: Path) -> dict[str, Any]:
    model = _get_whisper_model()

    segments_iter, info = model.transcribe(
        str(path),
        beam_size=settings.echryn_whisper_beam_size,
        vad_filter=True,
        vad_parameters={
            "threshold": settings.echryn_vad_threshold,
            "min_speech_duration_ms": settings.echryn_vad_min_speech_ms,
            "min_silence_duration_ms": settings.echryn_vad_min_silence_ms,
            "speech_pad_ms": settings.echryn_vad_speech_pad_ms,
        },
        word_timestamps=True,
        condition_on_previous_text=False,
        temperature=0.0,
    )

    segments: list[dict[str, Any]] = []
    text_parts: list[str] = []

    for segment in segments_iter:
        text = (segment.text or "").strip()
        if not text:
            continue

        no_speech_probability = float(getattr(segment, "no_speech_prob", 0.0) or 0.0)
        average_log_probability = float(getattr(segment, "avg_logprob", 0.0) or 0.0)

        words: list[dict[str, Any]] = []
        for word in getattr(segment, "words", None) or []:
            words.append(
                {
                    "start": round(float(word.start), 3) if word.start is not None else None,
                    "end": round(float(word.end), 3) if word.end is not None else None,
                    "word": word.word,
                    "probability": round(float(word.probability), 4)
                    if getattr(word, "probability", None) is not None
                    else None,
                }
            )

        segments.append(
            {
                "start": round(float(segment.start), 3),
                "end": round(float(segment.end), 3),
                "text": text,
                "average_log_probability": round(average_log_probability, 4),
                "no_speech_probability": round(no_speech_probability, 4),
                "words": words,
            }
        )
        text_parts.append(text)

    return {
        "text": " ".join(text_parts).strip(),
        "language": getattr(info, "language", None),
        "language_probability": round(float(getattr(info, "language_probability", 0.0) or 0.0), 4),
        "segments": segments,
    }


async def speech_analyze(path: Path, native: dict[str, Any]) -> dict[str, Any]:
    policy = native_audio_policy(native)

    try:
        vad = await asyncio.to_thread(_vad_sync, path)
    except Exception as exc:
        return {
            "status": "failed",
            "source": "silero_vad",
            "reason": "speech_detection_failed",
            "error": str(exc),
            "exception_type": exc.__class__.__name__,
            "policy": policy,
        }

    detector = {
        "status": "available",
        "engine": "silero_vad",
        "duration_seconds": vad["duration_seconds"],
        "speech_seconds": vad["speech_seconds"],
        "speech_ratio": vad["speech_ratio"],
        "segments": vad["chunks_seconds"],
        "threshold": settings.echryn_vad_threshold,
    }

    if not vad["chunks"] or vad["speech_seconds"] < settings.echryn_min_total_speech_seconds:
        return {
            "status": "no_speech_detected",
            "source": "silero_vad",
            "reason": "no_useful_speech_detected",
            "policy": policy,
            "detector": detector,
        }

    try:
        transcript = await asyncio.to_thread(_transcribe_sync, path)
    except Exception as exc:
        return {
            "status": "failed",
            "source": "faster_whisper",
            "reason": "transcription_failed",
            "error": str(exc),
            "exception_type": exc.__class__.__name__,
            "policy": policy,
            "detector": detector,
        }

    model_info = {
        "engine": "faster_whisper",
        "model": settings.echryn_speech_model,
        "device": settings.echryn_speech_device,
        "compute_type": settings.echryn_speech_compute_type,
    }

    if not transcript["text"]:
        return {
            "status": "no_speech_detected",
            "source": "faster_whisper",
            "reason": "vad_detected_voice_but_transcript_was_empty",
            "policy": policy,
            "detector": detector,
            "model": model_info,
        }

    if transcript["language_probability"] < settings.echryn_speech_min_language_probability:
        return {
            "status": "low_confidence",
            "source": "faster_whisper",
            "reason": "language_detection_confidence_below_threshold",
            "policy": policy,
            "detector": detector,
            "model": model_info,
            "confidence": {
                "language": transcript["language"],
                "language_probability": transcript["language_probability"],
                "minimum_required": settings.echryn_speech_min_language_probability,
            },
            "value": transcript,
        }

    return {
        "status": "available",
        "source": "faster_whisper",
        "policy": policy,
        "detector": detector,
        "model": model_info,
        "value": transcript,
    }
