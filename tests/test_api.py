from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from db import crud

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def client(db_session_factory, monkeypatch):
    import dashboard.app as app_module

    monkeypatch.setattr(app_module, "SessionLocal", db_session_factory)

    with db_session_factory() as db:
        crud.create_session(db, "SES-TEST-API", datetime.now(IST), "v.mp4", "g.csv", is_demo=True)
        crud.create_detection(
            db, pothole_id="PTH-000001", track_id=1, session_id="SES-TEST-API",
            timestamp=datetime.now(IST).isoformat(), latitude=12.97, longitude=77.59,
            gps_accuracy=5.0, speed=5.0, bearing=90.0, gps_sync_method="interpolated",
            confidence=0.9, frame_count=5, severity="HIGH", city="Bengaluru", state="Karnataka",
            zone="Unknown", ward="Test Ward", locality="Test Locality", postcode="560001",
            formatted_address="Test Address", is_demo=True,
        )
        db.commit()

    return TestClient(app_module.app)


def test_stats_endpoint(client):
    resp = client.get("/api/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_potholes"] == 1
    assert body["high_severity"] == 1


def test_detections_endpoint(client):
    resp = client.get("/api/detections")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["pothole_id"] == "PTH-000001"


def test_detections_endpoint_filters_by_severity(client):
    resp = client.get("/api/detections", params={"severity": "LOW"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_detection_detail_endpoint(client):
    resp = client.get("/api/detections/PTH-000001")
    assert resp.status_code == 200
    assert resp.json()["ward"] == "Test Ward"


def test_detection_detail_404(client):
    resp = client.get("/api/detections/PTH-999999")
    assert resp.status_code == 404


def test_analytics_endpoint(client):
    resp = client.get("/api/analytics")
    assert resp.status_code == 200
    body = resp.json()
    assert "by_severity" in body
    assert "over_time" in body


def test_sessions_endpoint(client):
    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    assert resp.json()[0]["session_id"] == "SES-TEST-API"


def test_export_csv_endpoint(client):
    resp = client.get("/api/export/csv")
    assert resp.status_code == 200
    assert "PTH-000001" in resp.text


def test_export_json_endpoint(client):
    resp = client.get("/api/export/json")
    assert resp.status_code == 200
    assert resp.json()[0]["pothole_id"] == "PTH-000001"


def test_evidence_endpoint_404_when_no_image(client):
    resp = client.get("/api/evidence/PTH-000001/original")
    assert resp.status_code == 404
