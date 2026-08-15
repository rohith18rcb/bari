"""
tracking.py — thin wrapper around Ultralytics' built-in multi-object tracker
(ByteTrack by default; BoT-SORT also supported via config) so a pothole seen
in dozens of consecutive frames is followed as one track, not re-detected
from scratch every frame.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import numpy as np

from core.config import settings


@dataclass(frozen=True)
class FrameTracks:
    frame_index: int
    frame: np.ndarray
    track_ids: list[int]
    boxes_xyxy: list[tuple[float, float, float, float]]
    confidences: list[float]
    class_ids: list[int]


def track_video(
    model,
    source: str,
    conf: float | None = None,
    iou: float | None = None,
    device: str = "cpu",
    tracker: str | None = None,
) -> Iterator[FrameTracks]:
    """Stream a video through YOLO + ByteTrack, yielding per-frame track data.

    ``model`` is an already-loaded ``ultralytics.YOLO`` instance (passed in
    rather than loaded here so callers control model lifetime/reuse).
    """
    conf = conf if conf is not None else settings.confidence_threshold
    iou = iou if iou is not None else settings.iou_threshold
    tracker = tracker or settings.tracker

    stream = model.track(
        source=source, conf=conf, iou=iou, device=device, tracker=tracker,
        persist=True, stream=True, verbose=False,
    )

    for frame_index, result in enumerate(stream):
        track_ids: list[int] = []
        boxes_xyxy: list[tuple[float, float, float, float]] = []
        confidences: list[float] = []
        class_ids: list[int] = []

        if result.boxes is not None and result.boxes.id is not None:
            ids = result.boxes.id.int().cpu().tolist()
            xyxy = result.boxes.xyxy.cpu().tolist()
            confs = result.boxes.conf.cpu().tolist()
            clss = result.boxes.cls.int().cpu().tolist()
            for tid, box, c, cls in zip(ids, xyxy, confs, clss):
                track_ids.append(int(tid))
                boxes_xyxy.append((box[0], box[1], box[2], box[3]))
                confidences.append(float(c))
                class_ids.append(int(cls))

        yield FrameTracks(
            frame_index=frame_index,
            frame=result.orig_img,
            track_ids=track_ids,
            boxes_xyxy=boxes_xyxy,
            confidences=confidences,
            class_ids=class_ids,
        )
