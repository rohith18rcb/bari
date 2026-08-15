"""overlay.py — draws detection boxes and the confirmed-event info banner
onto video frames. Kept deliberately minimal (per spec: "do not overload
the screen" / "keep the overlay clean, not a fake movie interface").
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

BOX_COLOR = (60, 200, 255)  # BGR
BANNER_BG = (20, 20, 20)
BANNER_FG = (255, 255, 255)
BANNER_ACCENT = (60, 200, 255)


def draw_box(frame: np.ndarray, box_xyxy: tuple[float, float, float, float], label: str) -> None:
    x1, y1, x2, y2 = (int(v) for v in box_xyxy)
    cv2.rectangle(frame, (x1, y1), (x2, y2), BOX_COLOR, 2)
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    cv2.rectangle(frame, (x1, max(0, y1 - th - 8)), (x1 + tw + 6, y1), BOX_COLOR, -1)
    cv2.putText(frame, label, (x1 + 3, max(12, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)


@dataclass(frozen=True)
class BannerInfo:
    confidence: float
    location: str
    latitude: float
    longitude: float
    severity: str
    time_str: str


def draw_banner(frame: np.ndarray, info: BannerInfo) -> None:
    """Compact top-left info panel, shown briefly after a pothole is confirmed."""
    lines = [
        ("BARI", True),
        (f"POTHOLE DETECTED  {info.confidence * 100:.0f}%", False),
        (f"Location: {info.location}", False),
        (f"GPS: {info.latitude:.4f}, {info.longitude:.4f}", False),
        (f"Severity: {info.severity}", False),
        (f"Time: {info.time_str}", False),
    ]
    pad = 8
    line_h = 20
    width = 320
    height = pad * 2 + line_h * len(lines)

    overlay = frame.copy()
    cv2.rectangle(overlay, (10, 10), (10 + width, 10 + height), BANNER_BG, -1)
    frame[:] = cv2.addWeighted(overlay, 0.75, frame, 0.25, 0)

    y = 10 + pad + 14
    for text, is_title in lines:
        color = BANNER_ACCENT if is_title else BANNER_FG
        scale = 0.6 if is_title else 0.45
        weight = 2 if is_title else 1
        cv2.putText(frame, text, (10 + pad, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, weight, cv2.LINE_AA)
        y += line_h
