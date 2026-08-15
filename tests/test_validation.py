from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import cv2
import numpy as np
import pytest

from core.gps_sync import GPSPoint
from core.validation import ValidationError, validate_gps_points, validate_video

IST = ZoneInfo("Asia/Kolkata")


def _write_tiny_video(path: Path, frames: int = 10, fps: float = 5.0, size=(64, 48)) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    for _ in range(frames):
        writer.write(np.zeros((size[1], size[0], 3), dtype=np.uint8))
    writer.release()


def test_validate_video_missing_file_raises(tmp_path: Path):
    with pytest.raises(ValidationError):
        validate_video(tmp_path / "missing.mp4")


def test_validate_video_empty_file_raises(tmp_path: Path):
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    with pytest.raises(ValidationError):
        validate_video(empty)


def test_validate_video_valid_file(tmp_path: Path):
    video_path = tmp_path / "sample.mp4"
    _write_tiny_video(video_path, frames=10, fps=5.0)
    info = validate_video(video_path)
    assert info.frame_count >= 1
    assert info.fps > 0
    assert info.width == 64
    assert info.height == 48


def test_validate_gps_points_empty_raises():
    with pytest.raises(ValidationError):
        validate_gps_points([])


def test_validate_gps_points_flags_low_accuracy():
    points = [GPSPoint(datetime.now(IST), 12.97, 77.59, accuracy=200.0)]
    report = validate_gps_points(points, min_accuracy_meters=50.0)
    assert report.num_rejected == 1
    assert report.is_valid is True  # low accuracy is a warning, not fatal


def test_validate_gps_points_valid_report():
    points = [
        GPSPoint(datetime.now(IST), 12.97, 77.59, accuracy=5.0),
        GPSPoint(datetime.now(IST) + timedelta(seconds=1), 12.971, 77.591, accuracy=5.0),
    ]
    report = validate_gps_points(points)
    assert report.num_points == 2
    assert report.is_valid is True
