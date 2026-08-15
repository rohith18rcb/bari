"""
duplicate.py — Level-2 duplicate classification: has this physical pothole
already been recorded (possibly in a different session)?

Level-1 duplication (same pothole across nearby video frames) is handled by
object tracking + core.events.PotholeEventEngine and never reaches here.

This module only decides a *label* — NEW / POSSIBLE_DUPLICATE / KNOWN — for
a newly confirmed event based on GPS proximity + recency to previously
confirmed events. When uncertain, both detections are kept (nothing is ever
silently dropped); the label is metadata for review, not a hard merge.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class DuplicateStatus(str, Enum):
    NEW = "NEW"
    POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"
    KNOWN = "KNOWN"


@dataclass(frozen=True)
class DuplicateClassification:
    status: DuplicateStatus
    duplicate_of: Optional[str]
    distance_meters: Optional[float]


def classify(
    nearby: list[tuple[object, float]],
    distance_threshold_meters: float,
) -> DuplicateClassification:
    """``nearby`` is a list of (Detection, distance_meters) tuples, already
    filtered to the configured time window and sorted by distance ascending
    (as returned by db.crud.find_nearby_detections).

    - Nothing within threshold           -> NEW
    - Closest match within half-threshold -> KNOWN (high confidence it's the
      same physical pothole; still saved as its own record for evidence/
      history, just labeled)
    - Closest match within full threshold -> POSSIBLE_DUPLICATE (ambiguous;
      flagged for human review rather than auto-merged)
    """
    if not nearby:
        return DuplicateClassification(DuplicateStatus.NEW, None, None)

    closest_detection, distance = nearby[0]
    pothole_id = getattr(closest_detection, "pothole_id", None)

    if distance <= distance_threshold_meters / 2.0:
        return DuplicateClassification(DuplicateStatus.KNOWN, pothole_id, distance)

    if distance <= distance_threshold_meters:
        return DuplicateClassification(DuplicateStatus.POSSIBLE_DUPLICATE, pothole_id, distance)

    return DuplicateClassification(DuplicateStatus.NEW, None, None)
