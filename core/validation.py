"""validation.py — pre-flight validation for video + GPS pipeline inputs.

Fails fast with a specific, actionable error message rather than letting a
bad input surface as a confusing crash deep inside the pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2

from core.gps_sync import GPSPoint


class ValidationError(Exception):
    pass


@dataclass
class VideoInfo:
    path: Path
    fps: float
    frame_count: int
    width: int
    height: int
    duration_seconds: float


def validate_video(path: Path) -> VideoInfo:
    if not path.exists():
        raise ValidationError(f"Video file not found: {path}")
    if path.stat().st_size == 0:
        raise ValidationError(f"Video file is empty: {path}")

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValidationError(f"Could not open video (unsupported/corrupt codec?): {path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    if fps <= 0:
        raise ValidationError(f"Video reports invalid FPS ({fps}): {path}")
    if width <= 0 or height <= 0:
        raise ValidationError(f"Video reports invalid frame size ({width}x{height}): {path}")

    duration = frame_count / fps if frame_count > 0 else 0.0
    if frame_count <= 0:
        raise ValidationError(f"Video reports zero/unknown frame count: {path}")

    return VideoInfo(path=path, fps=fps, frame_count=frame_count, width=width, height=height, duration_seconds=duration)


@dataclass
class GPSValidationReport:
    num_points: int
    num_rejected: int
    start_time: object
    end_time: object
    issues: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.num_points > 0 and not any("FATAL" in i for i in self.issues)


def validate_gps_points(points: list[GPSPoint], min_accuracy_meters: float = 50.0) -> GPSValidationReport:
    if not points:
        raise ValidationError("No valid GPS points parsed (file empty or entirely malformed)")

    issues: list[str] = []
    rejected = 0
    for p in points:
        if not (-90.0 <= p.latitude <= 90.0):
            issues.append(f"FATAL: latitude out of range at {p.timestamp}: {p.latitude}")
        if not (-180.0 <= p.longitude <= 180.0):
            issues.append(f"FATAL: longitude out of range at {p.timestamp}: {p.longitude}")
        if p.accuracy and p.accuracy > min_accuracy_meters:
            rejected += 1  # not fatal - just noted, low-accuracy points are still usable, flagged downstream

    if rejected:
        issues.append(f"{rejected} point(s) exceed accuracy threshold of {min_accuracy_meters}m (kept, flagged low-accuracy)")

    return GPSValidationReport(
        num_points=len(points),
        num_rejected=rejected,
        start_time=points[0].timestamp,
        end_time=points[-1].timestamp,
        issues=issues,
    )
