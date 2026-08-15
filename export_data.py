"""
export_data.py — exports pothole detection records to CSV or JSON.

Usage:
    python export_data.py --format csv
    python export_data.py --format json --out data/output/potholes.json
    python export_data.py --format csv --zone Bommanahalli --severity HIGH
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
from pathlib import Path

from core.config import settings
from db import crud
from db.database import SessionLocal, init_db

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("bari.export")

FIELDS = [
    "pothole_id", "track_id", "session_id", "timestamp", "latitude", "longitude",
    "gps_accuracy", "speed", "bearing", "gps_sync_method", "confidence", "frame_count",
    "severity", "city", "state", "zone", "ward", "locality", "postcode", "formatted_address",
    "image_path", "annotated_image_path", "crop_image_path", "duplicate_status", "duplicate_of",
    "is_demo", "created_at",
]


def detection_to_dict(d) -> dict:
    return {field: getattr(d, field) for field in FIELDS}


def main() -> int:
    parser = argparse.ArgumentParser(description="Export BARI pothole detections")
    parser.add_argument("--format", choices=["csv", "json"], required=True)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--zone", type=str, default=None)
    parser.add_argument("--ward", type=str, default=None)
    parser.add_argument("--locality", type=str, default=None)
    parser.add_argument("--severity", type=str, default=None, choices=["LOW", "MEDIUM", "HIGH"])
    parser.add_argument("--session-id", type=str, default=None)
    parser.add_argument("--min-confidence", type=float, default=None)
    args = parser.parse_args()

    init_db()
    with SessionLocal() as db:
        detections = crud.list_detections(
            db, zone=args.zone, ward=args.ward, locality=args.locality, severity=args.severity,
            session_id=args.session_id, min_confidence=args.min_confidence, limit=100000,
        )
        rows = [detection_to_dict(d) for d in detections]

    out_path = args.out or (settings.output_path / f"potholes.{args.format}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if args.format == "csv":
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
    else:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2, default=str)

    logger.info("Exported %d record(s) to %s", len(rows), out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
