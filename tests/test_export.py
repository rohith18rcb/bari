from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from db import crud
from export_data import FIELDS, detection_to_dict

IST = ZoneInfo("Asia/Kolkata")


def _seed(db):
    crud.create_session(db, "SES-TEST-EXPORT", datetime.now(IST), "v.mp4", "g.csv", is_demo=True)
    crud.create_detection(
        db, pothole_id="PTH-000001", track_id=1, session_id="SES-TEST-EXPORT",
        timestamp=datetime.now(IST).isoformat(), latitude=12.97, longitude=77.59,
        gps_accuracy=5.0, speed=5.0, bearing=90.0, gps_sync_method="interpolated",
        confidence=0.9, frame_count=5, severity="HIGH", city="Bengaluru", state="Karnataka",
        zone="Unknown", ward="Test Ward", locality="Test Locality", postcode="560001",
        formatted_address="Test Address", is_demo=True,
    )
    db.commit()


def test_detection_to_dict_has_all_fields(db_session):
    _seed(db_session)
    d = crud.get_detection(db_session, "PTH-000001")
    row = detection_to_dict(d)
    assert set(row.keys()) == set(FIELDS)
    assert row["pothole_id"] == "PTH-000001"
    assert row["severity"] == "HIGH"


def test_csv_export_roundtrip(db_session, tmp_path: Path):
    _seed(db_session)
    detections = crud.list_detections(db_session)
    rows = [detection_to_dict(d) for d in detections]

    out_path = tmp_path / "out.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    with open(out_path, encoding="utf-8") as f:
        read_back = list(csv.DictReader(f))
    assert len(read_back) == 1
    assert read_back[0]["pothole_id"] == "PTH-000001"


def test_json_export_roundtrip(db_session, tmp_path: Path):
    _seed(db_session)
    detections = crud.list_detections(db_session)
    rows = [detection_to_dict(d) for d in detections]

    out_path = tmp_path / "out.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, default=str)

    with open(out_path, encoding="utf-8") as f:
        read_back = json.load(f)
    assert len(read_back) == 1
    assert read_back[0]["severity"] == "HIGH"
