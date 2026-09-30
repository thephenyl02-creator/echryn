from pathlib import Path

from PIL import Image

from app.services.media import (
    _hamming_distance,
    select_representative_frame_indices,
)


def _write_solid(path: Path, value: int) -> None:
    Image.new("L", (32, 32), color=value).save(path)


def _write_split(path: Path, left: int, right: int) -> None:
    image = Image.new("L", (32, 32), color=left)
    for x in range(16, 32):
        for y in range(32):
            image.putpixel((x, y), right)
    image.save(path)


def test_hamming_distance():
    assert _hamming_distance(0b0000, 0b0000) == 0
    assert _hamming_distance(0b0000, 0b1111) == 4


def test_representative_selection_removes_duplicates(tmp_path):
    frames = []
    for index in range(8):
        path = tmp_path / f"frame-{index}.png"
        if index < 4:
            _write_split(path, 0, 255)
        else:
            _write_split(path, 255, 0)
        frames.append(path)

    selected = select_representative_frame_indices(frames, limit=6)

    assert len(selected) == 2
    assert selected[0] == 0
    assert selected[-1] == 4


def test_representative_selection_respects_limit(tmp_path):
    frames = []
    patterns = [
        (0, 255),
        (32, 220),
        (64, 192),
        (96, 160),
        (128, 128),
        (160, 96),
        (192, 64),
        (220, 32),
    ]
    for index, (left, right) in enumerate(patterns):
        path = tmp_path / f"frame-{index}.png"
        _write_split(path, left, right)
        frames.append(path)

    selected = select_representative_frame_indices(frames, limit=4, duplicate_distance=0)

    assert len(selected) <= 4
    assert selected == sorted(selected)
