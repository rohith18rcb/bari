"""
dashboard/ingest.py — mobile ingestion API: receives session start/end and
individual geotagged photos from the Android companion app, runs them
through YOLO + the shared location/severity/duplicate pipeline (see
core/mobile_ingest.py), and stores confirmed detections in the same
database the laptop-video pipeline (main.py) writes to.

Mounted into dashboard/app.py under /api/mobile — the same dashboard the
laptop-video pipeline already populates, so mobile-sourced potholes show up
on the same map/analytics immediately.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from core.config import settings
from core.device import resolve_device
from core.gps_sync import parse_gps_csv
from core.geo_utils import filter_and_sum_distance
from core.ids import generate_session_id
from core.location import LocationEngine
from db import crud
from db.crud import PersistentGeocodeCache
from db.database import SessionLocal, get_session
from db.models import SessionRecord

logger = logging.getLogger("bari.ingest")
router = APIRouter(prefix="/api/mobile", tags=["mobile"])

IST = ZoneInfo("Asia/Kolkata")

_model = None
_model_load_failed_reason: Optional[str] = None


def _get_model():
    global _model, _model_load_failed_reason
    if _model is not None:
        return _model
    if _model_load_failed_reason is not None:
        return None
    if not settings.model_path.exists():
        _model_load_failed_reason = f"No trained model at {settings.model_path}. Train one first (ml/training/train.py)."
        logger.warning("Mobile ingest: %s", _model_load_failed_reason)
        return None
    from ultralytics import YOLO
    device = resolve_device(settings.device)
    logger.info("Mobile ingest: loading model %s (device=%s)", settings.model_path, device)
    _model = YOLO(str(settings.model_path))
    return _model


def _location_engine() -> LocationEngine:
    return LocationEngine(cache=PersistentGeocodeCache(get_session))


@router.post("/session/start")
def start_session(
    device_id: str = Form(...),
    session_id: Optional[str] = Form(None),
    start_time: Optional[str] = Form(None),
):
    """Creates a session record. Idempotent when ``session_id`` is supplied:
    the app generates its own session id locally (so a ride can start
    immediately with no network), then calls this endpoint in the
    background to sync it — possibly much later, once WiFi is available.
    Calling it again for an id that already exists just confirms it rather
    than erroring, so retries from an unreliable connection are safe.
    ``start_time`` (ISO 8601) lets the recorded start reflect when the ride
    actually began on the phone, not whenever this sync call happened to
    succeed.
    """
    with SessionLocal() as db:
        if session_id is not None:
            existing = db.get(SessionRecord, session_id)
            if existing is not None:
                return {"session_id": session_id}

        ts = datetime.now(IST)
        if start_time:
            try:
                parsed = datetime.fromisoformat(start_time)
                ts = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=IST)
            except ValueError:
                pass

        sid = session_id or generate_session_id(ts)
        crud.create_session(db, sid, ts, video_source=f"[MOBILE] {device_id}", gps_source="[MOBILE] on-device GPS per photo", is_demo=False)
        db.commit()
    logger.info("Mobile session started: %s (device=%s)", sid, device_id)
    return {"session_id": sid}


@router.post("/session/{session_id}/photo")
async def upload_photo(
    session_id: str,
    file: UploadFile = File(...),
    timestamp: str = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    accuracy: float = Form(0.0),
    speed: float = Form(0.0),
    bearing: float = Form(0.0),
):
    model = _get_model()
    if model is None:
        raise HTTPException(status_code=503, detail=_model_load_failed_reason or "Model unavailable")

    if not (-90.0 <= latitude <= 90.0) or not (-180.0 <= longitude <= 180.0):
        raise HTTPException(status_code=400, detail="latitude/longitude out of range")

    raw = await file.read()
    array = np.frombuffer(raw, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=400, detail="Could not decode image")

    try:
        ts = datetime.fromisoformat(timestamp)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=IST)
    except ValueError:
        raise HTTPException(status_code=400, detail="timestamp must be ISO 8601")

    from core.mobile_ingest import process_mobile_photo

    with SessionLocal() as db:
        if db.get(SessionRecord, session_id) is None:
            raise HTTPException(status_code=404, detail=f"Unknown session_id: {session_id}. Call /api/mobile/session/start first.")
        result = process_mobile_photo(
            db, model, session_id, image, ts, latitude, longitude, accuracy, speed, bearing,
            location_engine=_location_engine(),
        )
        db.commit()

    if result.detected:
        logger.info("Mobile photo -> %s confirmed (conf=%.2f, severity=%s, dup=%s, ward=%s)",
                     result.pothole_id, result.confidence, result.severity, result.duplicate_status, result.ward)
    return {
        "detected": result.detected,
        "pothole_id": result.pothole_id,
        "confidence": result.confidence,
        "severity": result.severity,
        "duplicate_status": result.duplicate_status,
        "ward": result.ward,
    }


@router.post("/session/{session_id}/end")
async def end_session(session_id: str, gps_trace: UploadFile = File(...)):
    """``gps_trace`` is a CSV in the same schema core/gps_sync.py already
    parses (timestamp,latitude,longitude,accuracy,speed,bearing) — the
    phone's full GPS log for the ride, used only to compute distance
    traveled (individual photo detections already carry their own GPS)."""
    import tempfile
    from pathlib import Path

    raw = await gps_trace.read()
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        tmp.write(raw)
        tmp_path = Path(tmp.name)

    try:
        points = parse_gps_csv(tmp_path)
    except ValueError:
        # No valid GPS points were ever recorded for this ride (e.g. the browser
        # never got a location fix) — finalize with zero distance rather than
        # failing the whole "stop ride" action; individual photo detections
        # (if any) already carry their own GPS and are unaffected.
        points = []
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=f"Invalid GPS trace: {e}")
    finally:
        tmp_path.unlink(missing_ok=True)

    coords = [(p.latitude, p.longitude) for p in points]
    intervals = [(points[i + 1].timestamp - points[i].timestamp).total_seconds() for i in range(len(points) - 1)]
    dist = filter_and_sum_distance(coords, intervals_seconds=intervals)

    end_time = points[-1].timestamp if points else datetime.now(IST)
    duration = (points[-1].timestamp - points[0].timestamp).total_seconds() if len(points) >= 2 else 0.0

    with SessionLocal() as db:
        total_detections = len(crud.list_detections(db, session_id=session_id, limit=100000))
        crud.finalize_session(db, session_id, end_time=end_time, distance_km=dist.total_distance_km,
                               duration_seconds=duration, total_detections=total_detections)
        db.commit()

    logger.info("Mobile session ended: %s (%.2f km, %d detections)", session_id, dist.total_distance_km, total_detections)
    return {"session_id": session_id, "distance_km": dist.total_distance_km, "total_detections": total_detections}
