"""
events.py — the Pothole Event Engine.

Turns a stream of per-frame, per-track detections into confirmed pothole
*events*. A tracked object is not "counted" the moment YOLO first sees it —
that would double count the same physical pothole across dozens of frames
(Level-1 duplication). Instead, each track_id accumulates evidence
(confidence, bounding box, frame span) until it has been seen for at least
``MIN_TRACK_FRAMES`` frames, at which point it is confirmed exactly once.

Level-2 duplication (the same physical pothole seen again later — a
different pass, a different session) is *not* handled here: it requires GPS
+ database lookups and is handled by the caller (main.py) via
db.crud.find_nearby_detections once an event is confirmed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.config import settings


@dataclass
class TrackAccumulator:
    track_id: int
    frame_indices: list[int] = field(default_factory=list)
    confidences: list[float] = field(default_factory=list)
    boxes_xyxy: list[tuple[float, float, float, float]] = field(default_factory=list)
    confirmed: bool = False

    @property
    def frame_count(self) -> int:
        return len(self.frame_indices)

    @property
    def mean_confidence(self) -> float:
        return sum(self.confidences) / len(self.confidences) if self.confidences else 0.0

    @property
    def best_frame_idx(self) -> int:
        """Index (into this accumulator's lists) of the frame with the highest
        confidence — used as the representative box/frame for evidence."""
        return max(range(len(self.confidences)), key=lambda i: self.confidences[i])

    @property
    def representative_box(self) -> tuple[float, float, float, float]:
        return self.boxes_xyxy[self.best_frame_idx]

    @property
    def representative_frame_index(self) -> int:
        return self.frame_indices[self.best_frame_idx]

    @property
    def first_frame_index(self) -> int:
        return self.frame_indices[0]

    @property
    def last_frame_index(self) -> int:
        return self.frame_indices[-1]


@dataclass(frozen=True)
class ConfirmedEvent:
    track_id: int
    frame_count: int
    mean_confidence: float
    representative_box_xyxy: tuple[float, float, float, float]
    representative_frame_index: int
    first_frame_index: int
    last_frame_index: int


class PotholeEventEngine:
    """Accumulates per-track detections and confirms events once persistence
    threshold is reached. Also emits an updated snapshot for already-confirmed
    tracks so a caller can, e.g., refine the representative box as more
    (possibly more confident) frames arrive — but each track is only ever
    "newly confirmed" once.
    """

    def __init__(self, min_track_frames: Optional[int] = None):
        self.min_track_frames = min_track_frames if min_track_frames is not None else settings.min_track_frames
        self._tracks: dict[int, TrackAccumulator] = {}

    def update(self, track_id: int, frame_index: int, confidence: float, box_xyxy: tuple[float, float, float, float]) -> Optional[ConfirmedEvent]:
        """Feed one detection for a track. Returns a ConfirmedEvent the first
        time this track crosses the persistence threshold, else None.
        """
        acc = self._tracks.get(track_id)
        if acc is None:
            acc = TrackAccumulator(track_id=track_id)
            self._tracks[track_id] = acc

        acc.frame_indices.append(frame_index)
        acc.confidences.append(confidence)
        acc.boxes_xyxy.append(box_xyxy)

        if not acc.confirmed and acc.frame_count >= self.min_track_frames:
            acc.confirmed = True
            return ConfirmedEvent(
                track_id=acc.track_id,
                frame_count=acc.frame_count,
                mean_confidence=acc.mean_confidence,
                representative_box_xyxy=acc.representative_box,
                representative_frame_index=acc.representative_frame_index,
                first_frame_index=acc.first_frame_index,
                last_frame_index=acc.last_frame_index,
            )
        return None

    def get_accumulator(self, track_id: int) -> Optional[TrackAccumulator]:
        return self._tracks.get(track_id)

    def confirmed_track_ids(self) -> list[int]:
        return [tid for tid, acc in self._tracks.items() if acc.confirmed]

    def unconfirmed_track_count(self) -> int:
        return sum(1 for acc in self._tracks.values() if not acc.confirmed)
