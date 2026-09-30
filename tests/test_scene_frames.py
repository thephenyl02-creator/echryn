from pathlib import Path

from app.services.media import _build_frame_timestamps, _frame_timestamp_seconds


def test_scene_timestamps_keep_cuts_and_temporal_coverage():
    timestamps = _build_frame_timestamps(
        duration_seconds=15.0,
        scene_timestamps=[1.2, 1.3, 4.8, 9.1, 13.7],
        limit=8,
        min_gap_seconds=0.6,
    )

    assert timestamps[0] == 0.0
    assert timestamps[-1] == 14.95
    assert 1.2 in timestamps
    assert 4.8 in timestamps
    assert 9.1 in timestamps
    assert len(timestamps) <= 8


def test_scene_timestamp_builder_supplements_when_no_cuts():
    timestamps = _build_frame_timestamps(
        duration_seconds=12.0,
        scene_timestamps=[],
        limit=6,
        min_gap_seconds=0.6,
    )

    assert len(timestamps) == 6
    assert timestamps[0] == 0.0
    assert timestamps[-1] == 11.95


def test_scene_timestamp_builder_deduplicates_close_cuts():
    timestamps = _build_frame_timestamps(
        duration_seconds=8.0,
        scene_timestamps=[2.0, 2.2, 2.4, 5.0],
        limit=8,
        min_gap_seconds=0.6,
    )

    assert 2.0 in timestamps
    assert 2.2 not in timestamps
    assert 2.4 not in timestamps
    assert 5.0 in timestamps


def test_frame_timestamp_is_read_from_filename():
    path = Path("frame-004-t7.325.jpg")
    assert _frame_timestamp_seconds(path, 4) == 7.325
