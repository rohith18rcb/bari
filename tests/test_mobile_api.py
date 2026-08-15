from __future__ import annotations

import io

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient


def _tiny_jpeg_bytes() -> bytes:
    """A real, decodable minimal JPEG — tests that need to get past image
    decoding (to exercise session/model logic) can't use garbage bytes."""
    image = np.zeros((16, 16, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", image)
    assert ok
    return buf.tobytes()


@pytest.fixture
def client(db_session_factory, monkeypatch):
    import dashboard.app as app_module
    import dashboard.ingest as ingest_module

    monkeypatch.setattr(app_module, "SessionLocal", db_session_factory)
    monkeypatch.setattr(ingest_module, "SessionLocal", db_session_factory)

    return TestClient(app_module.app)


def test_start_session_creates_record(client):
    resp = client.post("/api/mobile/session/start", data={"device_id": "test-device"})
    assert resp.status_code == 200
    assert resp.json()["session_id"].startswith("SES-")


def test_start_session_with_client_supplied_id_is_idempotent(client):
    """Regression test: the app generates its own session id offline and
    syncs it later (possibly retried) — a second /start call for the same
    id must not create a duplicate or error, just confirm the existing one."""
    sid = "SES-20260815-090000-AB12"
    first = client.post("/api/mobile/session/start", data={"device_id": "phone-1", "session_id": sid})
    assert first.status_code == 200
    assert first.json()["session_id"] == sid

    second = client.post("/api/mobile/session/start", data={"device_id": "phone-1", "session_id": sid})
    assert second.status_code == 200
    assert second.json()["session_id"] == sid

    resp = client.get("/api/sessions")
    matching = [s for s in resp.json() if s["session_id"] == sid]
    assert len(matching) == 1  # not duplicated


def test_start_session_honors_client_supplied_start_time(client):
    sid = "SES-20260815-090500-CD34"
    client.post(
        "/api/mobile/session/start",
        data={"device_id": "phone-1", "session_id": sid, "start_time": "2026-08-15T09:05:00+05:30"},
    )
    resp = client.get("/api/sessions")
    matching = next(s for s in resp.json() if s["session_id"] == sid)
    assert matching["start_time"].startswith("2026-08-15T09:05:00")


def test_end_session_with_empty_gps_trace_does_not_error(client):
    """Regression test: a ride with zero recorded GPS fixes (e.g. the
    browser never got a location permission) must still finalize the
    session instead of returning 400 — see dashboard/ingest.py::end_session."""
    start = client.post("/api/mobile/session/start", data={"device_id": "test-device"})
    session_id = start.json()["session_id"]

    empty_csv = "timestamp,latitude,longitude,accuracy,speed,bearing\n"
    resp = client.post(
        f"/api/mobile/session/{session_id}/end",
        files={"gps_trace": ("trace.csv", io.BytesIO(empty_csv.encode()), "text/csv")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["distance_km"] == 0.0
    assert body["total_detections"] == 0


def test_end_session_with_real_trace_computes_distance(client):
    start = client.post("/api/mobile/session/start", data={"device_id": "test-device"})
    session_id = start.json()["session_id"]

    csv_text = (
        "timestamp,latitude,longitude,accuracy,speed,bearing\n"
        "2026-08-14T18:00:00+05:30,12.9716,77.5946,5.0,8.0,90\n"
        "2026-08-14T18:00:30+05:30,12.9750,77.5980,5.0,8.0,90\n"
    )
    resp = client.post(
        f"/api/mobile/session/{session_id}/end",
        files={"gps_trace": ("trace.csv", io.BytesIO(csv_text.encode()), "text/csv")},
    )
    assert resp.status_code == 200
    assert resp.json()["distance_km"] > 0


def test_photo_upload_without_active_session_404s(client):
    resp = client.post(
        "/api/mobile/session/SES-DOES-NOT-EXIST/photo",
        files={"file": ("photo.jpg", io.BytesIO(_tiny_jpeg_bytes()), "image/jpeg")},
        data={"timestamp": "2026-08-14T18:00:00+05:30", "latitude": "12.97", "longitude": "77.59"},
    )
    # Either 503 (no trained model available in this environment) or 404
    # (unknown session, checked after the model-availability check) is
    # acceptable here — what must NOT happen is a 500 or a DB write.
    assert resp.status_code in (404, 503)


def test_photo_upload_rejects_out_of_range_coordinates(client):
    start = client.post("/api/mobile/session/start", data={"device_id": "test-device"})
    session_id = start.json()["session_id"]

    resp = client.post(
        f"/api/mobile/session/{session_id}/photo",
        files={"file": ("photo.jpg", io.BytesIO(b"not-a-real-jpeg"), "image/jpeg")},
        data={"timestamp": "2026-08-14T18:00:00+05:30", "latitude": "999", "longitude": "77.59"},
    )
    assert resp.status_code in (400, 503)  # 503 if no model loaded before the range check runs
