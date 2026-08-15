"""evidence.py — saves the 3 evidence images for a confirmed pothole event."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from core.config import settings

_SAFE_ID = re.compile(r"^PTH-\d{6}$")


@dataclass(frozen=True)
class EvidencePaths:
    original: Path
    annotated: Path
    crop: Path


def _sanitize_pothole_id(pothole_id: str) -> str:
    if not _SAFE_ID.match(pothole_id):
        raise ValueError(f"Refusing to save evidence for unexpected pothole_id format: {pothole_id!r}")
    return pothole_id


def evidence_dir_for(timestamp: datetime, base: Path | None = None) -> Path:
    base = base or settings.evidence_path
    return base / f"{timestamp.year:04d}" / f"{timestamp.month:02d}" / f"{timestamp.day:02d}"


def save_evidence(
    pothole_id: str,
    timestamp: datetime,
    original_frame: np.ndarray,
    annotated_frame: np.ndarray,
    box_xyxy: tuple[float, float, float, float],
    base_dir: Path | None = None,
) -> EvidencePaths:
    """Save original / annotated / cropped evidence images for one confirmed event."""
    safe_id = _sanitize_pothole_id(pothole_id)
    out_dir = evidence_dir_for(timestamp, base_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    original_path = out_dir / f"{safe_id}.jpg"
    annotated_path = out_dir / f"{safe_id}_annotated.jpg"
    crop_path = out_dir / f"{safe_id}_crop.jpg"

    h, w = original_frame.shape[:2]
    x1, y1, x2, y2 = box_xyxy
    x1, y1 = max(0, int(x1)), max(0, int(y1))
    x2, y2 = min(w, int(x2)), min(h, int(y2))
    crop = original_frame[y1:y2, x1:x2] if x2 > x1 and y2 > y1 else original_frame

    cv2.imwrite(str(original_path), original_frame)
    cv2.imwrite(str(annotated_path), annotated_frame)
    cv2.imwrite(str(crop_path), crop)

    return EvidencePaths(original=original_path, annotated=annotated_path, crop=crop_path)
