"""
dashboard/app.py — FastAPI backend for the BARI dashboard: stats, map data,
analytics, filterable detection table, evidence images, and CSV/JSON export.

Usage:
    python dashboard/app.py
    # or: uvicorn dashboard.app:app --reload --port 8000
"""
from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from core.config import settings
from db import crud
from db.database import SessionLocal, init_db
from export_data import FIELDS, detection_to_dict

app = FastAPI(title="BARI — Bengaluru AI Road Intelligence")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

init_db()

from dashboard.ingest import router as mobile_ingest_router  # noqa: E402
app.include_router(mobile_ingest_router)

STATIC_DIR = Path(__file__).resolve().parent / "static"
EVIDENCE_KINDS = {"original": "image_path", "annotated": "annotated_image_path", "crop": "crop_image_path"}


@app.get("/api/stats")
def api_stats():
    with SessionLocal() as db:
        return crud.get_stats(db)


@app.get("/api/analytics")
def api_analytics():
    with SessionLocal() as db:
        return crud.get_analytics(db)


@app.get("/api/sessions")
def api_sessions():
    with SessionLocal() as db:
        sessions = crud.list_sessions(db)
        return [
            {
                "session_id": s.session_id, "start_time": s.start_time, "end_time": s.end_time,
                "distance_km": s.distance_km, "duration_seconds": s.duration_seconds,
                "total_detections": s.total_detections, "is_demo": s.is_demo,
            }
            for s in sessions
        ]


@app.get("/api/detections")
def api_detections(
    zone: Optional[str] = None,
    ward: Optional[str] = None,
    locality: Optional[str] = None,
    severity: Optional[str] = None,
    session_id: Optional[str] = None,
    min_confidence: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = Query(default=5000, le=100000),
):
    with SessionLocal() as db:
        detections = crud.list_detections(
            db, zone=zone, ward=ward, locality=locality, severity=severity, session_id=session_id,
            min_confidence=min_confidence, start_date=start_date, end_date=end_date, limit=limit,
        )
        return [detection_to_dict(d) for d in detections]


@app.get("/api/detections/{pothole_id}")
def api_detection_detail(pothole_id: str):
    with SessionLocal() as db:
        d = crud.get_detection(db, pothole_id)
        if d is None:
            raise HTTPException(status_code=404, detail="Not found")
        return detection_to_dict(d)


@app.delete("/api/detections/{pothole_id}")
def api_delete_detection(pothole_id: str):
    """Removes a detection — e.g. a false positive — from the database and
    deletes its evidence images from disk. Irreversible; the dashboard
    confirms with the user before calling this."""
    evidence_root = settings.evidence_path.resolve()
    with SessionLocal() as db:
        d = crud.get_detection(db, pothole_id)
        if d is None:
            raise HTTPException(status_code=404, detail="Not found")
        evidence_paths = [d.image_path, d.annotated_image_path, d.crop_image_path]
        crud.delete_detection(db, pothole_id)
        db.commit()

    for path_str in evidence_paths:
        if not path_str:
            continue
        path = Path(path_str).resolve()
        if evidence_root in path.parents and path.exists():
            path.unlink(missing_ok=True)

    return {"deleted": pothole_id}


@app.get("/api/evidence/{pothole_id}/{kind}")
def api_evidence(pothole_id: str, kind: str):
    if kind not in EVIDENCE_KINDS:
        raise HTTPException(status_code=400, detail="kind must be one of: original, annotated, crop")
    with SessionLocal() as db:
        d = crud.get_detection(db, pothole_id)
        if d is None:
            raise HTTPException(status_code=404, detail="Not found")
        path_str = getattr(d, EVIDENCE_KINDS[kind])

    if not path_str:
        raise HTTPException(status_code=404, detail="No evidence image recorded for this detection")

    path = Path(path_str).resolve()
    evidence_root = settings.evidence_path.resolve()
    if evidence_root not in path.parents or not path.exists():
        raise HTTPException(status_code=404, detail="Evidence image not found")

    return FileResponse(path)


@app.get("/api/export/csv")
def api_export_csv():
    with SessionLocal() as db:
        rows = [detection_to_dict(d) for d in crud.list_detections(db, limit=100000)]

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=potholes.csv"},
    )


@app.get("/api/export/json")
def api_export_json():
    with SessionLocal() as db:
        rows = [detection_to_dict(d) for d in crud.list_detections(db, limit=100000)]
    payload = json.dumps(rows, indent=2, default=str)
    return StreamingResponse(
        iter([payload]), media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=potholes.json"},
    )


@app.get("/BARI-Collector.apk")
def download_apk():
    """Served with the explicit Android package MIME type so phone browsers
    trigger the system installer on tap, instead of treating it as an
    opaque/unknown file (StaticFiles' generic MIME guessing doesn't know
    the .apk extension)."""
    apk_path = STATIC_DIR / "BARI-Collector.apk"
    if not apk_path.exists():
        raise HTTPException(status_code=404, detail="APK not built yet")
    return FileResponse(
        apk_path,
        media_type="application/vnd.android.package-archive",
        filename="BARI-Collector.apk",
    )


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("dashboard.app:app", host=settings.dashboard_host, port=settings.dashboard_port, reload=False)
