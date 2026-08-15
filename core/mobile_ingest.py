"""
mobile_ingest.py — confirmation logic for pothole detections submitted as
single photos from the Android companion app (as opposed to main.py's video
pipeline, which sees a dense frame stream and tracks objects across frames).

Why single-photo confirmation is different from the video path:
  - There is no consecutive-frame track to accumulate persistence evidence
    from (core/events.py's MIN_TRACK_FRAMES logic doesn't apply to one
    isolated photo) — a photo is confirmed the moment YOLO detects a
    pothole in it above the configured confidence threshold.
  - Level-1 duplicate suppression (same pothole, same pass, via tracking)
    is therefore not applicable. Level-2 duplicate suppression (GPS
    proximity + recency against previously confirmed events, from
    core/duplicate.py) becomes the *only* line of defense against
    recording the same physical pothole twice — which is exactly what it
    was already designed for, so it's reused unchanged.
  - GPS is not synchronized/interpolated (core/gps_sync.py) because each
    photo already carries its own on-device GPS fix taken at capture time
    — there's no separate video-clock/GPS-clock alignment problem to solve.

This module is intentionally separate from main.py's `_confirm_event` (which
is video/tracking-specific) but shares every other building block: severity,
location, duplicate classification, evidence saving, and the DB layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import numpy as np

from core.config import settings
from core.duplicate import classify as classify_duplicate
from core.evidence import save_evidence
from core.ids import format_pothole_id
from core.location import LocationEngine
from core.overlay import draw_box
from core.severity import SeverityInputs, estimate_severity
from db import crud
from sqlalchemy.orm import Session as DBSession

MOBILE_TRACK_ID = -1  # sentinel: "no video track — single mobile photo"
GPS_SYNC_METHOD_DEVICE = "device_reported"


@dataclass(frozen=True)
class MobilePhotoResult:
    detected: bool
    pothole_id: Optional[str]
    confidence: Optional[float]
    severity: Optional[str]
    duplicate_status: Optional[str]
    ward: Optional[str]


def process_mobile_photo(
    db: DBSession,
    model,
    session_id: str,
    image: np.ndarray,
    timestamp: datetime,
    latitude: float,
    longitude: float,
    accuracy: float,
    speed: float,
    bearing: float,
    location_engine: LocationEngine,
    conf_threshold: Optional[float] = None,
    iou_threshold: Optional[float] = None,
) -> MobilePhotoResult:
    conf_threshold = conf_threshold if conf_threshold is not None else settings.confidence_threshold
    iou_threshold = iou_threshold if iou_threshold is not None else settings.iou_threshold

    results = model.predict(image, conf=conf_threshold, iou=iou_threshold, verbose=False)
    boxes = results[0].boxes if results else None

    if boxes is None or len(boxes) == 0:
        return MobilePhotoResult(detected=False, pothole_id=None, confidence=None, severity=None, duplicate_status=None, ward=None)

    confidences = boxes.conf.cpu().tolist()
    xyxy = boxes.xyxy.cpu().tolist()
    best_idx = max(range(len(confidences)), key=lambda i: confidences[i])
    best_box = tuple(xyxy[best_idx])
    best_conf = float(confidences[best_idx])

    h, w = image.shape[:2]
    severity = estimate_severity(SeverityInputs(
        box_width=best_box[2] - best_box[0], box_height=best_box[3] - best_box[1],
        frame_width=w, frame_height=h, frame_count=1, mean_confidence=best_conf,
    ))

    loc = location_engine.resolve(latitude, longitude)

    nearby = crud.find_nearby_detections(
        db, latitude, longitude, settings.duplicate_distance_meters,
        settings.duplicate_time_window_hours, reference_time=timestamp,
    )
    dup = classify_duplicate(nearby, settings.duplicate_distance_meters)

    pothole_id = format_pothole_id(crud.next_pothole_sequence(db))

    annotated = image.copy()
    draw_box(annotated, best_box, f"POTHOLE {best_conf * 100:.0f}%")
    evidence = save_evidence(pothole_id, timestamp, image, annotated, best_box)

    crud.create_detection(
        db,
        pothole_id=pothole_id, track_id=MOBILE_TRACK_ID, session_id=session_id,
        timestamp=timestamp.isoformat(), latitude=latitude, longitude=longitude,
        gps_accuracy=accuracy, speed=speed, bearing=bearing, gps_sync_method=GPS_SYNC_METHOD_DEVICE,
        confidence=best_conf, frame_count=1, severity=severity.severity.value,
        city=loc.city, state=loc.state, zone=loc.zone, ward=loc.ward, locality=loc.locality,
        postcode=loc.postcode, formatted_address=loc.formatted_address,
        image_path=str(evidence.original), annotated_image_path=str(evidence.annotated), crop_image_path=str(evidence.crop),
        duplicate_status=dup.status.value, duplicate_of=dup.duplicate_of,
        is_demo=False,
    )

    return MobilePhotoResult(
        detected=True, pothole_id=pothole_id, confidence=best_conf,
        severity=severity.severity.value, duplicate_status=dup.status.value, ward=loc.ward,
    )
