"""
generate_demo_data.py — populates the database with a richer set of
simulated sessions + pothole detections spread across Bengaluru, so the
dashboard/map/analytics have enough data to be meaningfully demonstrated
without requiring dozens of real road videos.

Every record inserted by this script is flagged `is_demo=True` in the
database and should be shown to the user as clearly-labeled DEMO DATA by
the dashboard — never presented as a real observation.

Ward is resolved using the REAL BBMP ward boundary GeoJSON (point-in-polygon
lookup) even for these simulated points, and (optionally) locations are
reverse-geocoded through the real Nominatim service — only the point
(that a pothole exists here, with this severity) is simulated.

Usage:
    python scripts/generate_demo_data.py --sessions 8 --min-per-session 6 --max-per-session 16
"""
from __future__ import annotations

import argparse
import logging
import random
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import cv2
import numpy as np

import sys
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.config import settings
from core.duplicate import classify as classify_duplicate
from core.evidence import save_evidence
from core.geo_utils import filter_and_sum_distance
from core.ids import format_pothole_id, generate_session_id
from core.location import LocationEngine
from core.overlay import draw_box
from core.severity import Severity, SeverityInputs, estimate_severity
from db import crud
from db.crud import PersistentGeocodeCache
from db.database import SessionLocal, get_session, init_db
from scripts.generate_demo_gps import WAYPOINTS

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("bari.generate_demo_data")

IST = ZoneInfo("Asia/Kolkata")
TEST_IMAGES_DIR = PROJECT_ROOT / "ml" / "datasets" / "processed" / "test" / "images"


def _route_point(progress: float, rng: random.Random) -> tuple[float, float]:
    segments = len(WAYPOINTS) - 1
    seg_progress = progress * segments
    seg_idx = min(int(seg_progress), segments - 1)
    local_t = seg_progress - seg_idx
    _, lat1, lon1 = WAYPOINTS[seg_idx]
    _, lat2, lon2 = WAYPOINTS[seg_idx + 1]
    lat = lat1 + (lat2 - lat1) * local_t + rng.uniform(-0.0015, 0.0015)
    lon = lon1 + (lon2 - lon1) * local_t + rng.uniform(-0.0015, 0.0015)
    return lat, lon


def _fake_evidence(pothole_id: str, timestamp: datetime, sample_images: list[Path], rng: random.Random, severity: Severity):
    """Reuses a real (licensed) dataset photo as stand-in evidence for a
    simulated demo detection, clearly namespaced under a DEMO session."""
    img_path = rng.choice(sample_images)
    img = cv2.imread(str(img_path))
    if img is None:
        img = np.zeros((480, 640, 3), dtype=np.uint8)
    h, w = img.shape[:2]
    bw, bh = w * rng.uniform(0.15, 0.4), h * rng.uniform(0.15, 0.4)
    x1 = rng.uniform(0, w - bw)
    y1 = rng.uniform(0, h - bh)
    box = (x1, y1, x1 + bw, y1 + bh)

    annotated = img.copy()
    draw_box(annotated, box, f"POTHOLE {rng.randint(40, 98)}%")

    return save_evidence(pothole_id, timestamp, img, annotated, box)


def generate(sessions: int, min_per: int, max_per: int, geocode: bool, seed: int) -> int:
    init_db()
    rng = random.Random(seed)
    sample_images = sorted(p for p in TEST_IMAGES_DIR.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"}) if TEST_IMAGES_DIR.exists() else []
    if not sample_images:
        logger.warning("No sample images found at %s; demo evidence images will be blank placeholders", TEST_IMAGES_DIR)

    location_engine = LocationEngine(cache=PersistentGeocodeCache(get_session), geocode_enabled=geocode)

    now = datetime.now(IST)
    total_detections = 0

    for s in range(sessions):
        session_start = now - timedelta(days=rng.randint(0, 28), hours=rng.randint(0, 23), minutes=rng.randint(0, 59))
        session_id = generate_session_id(session_start)
        n_detections = rng.randint(min_per, max_per)

        route_points = [_route_point(i / 50, rng) for i in range(51)]
        dist = filter_and_sum_distance(route_points)

        with SessionLocal() as db:
            crud.create_session(db, session_id, session_start, video_source="[DEMO] simulated", gps_source="[DEMO] simulated", is_demo=True)
            db.commit()

        for d in range(n_detections):
            progress = rng.random()
            lat, lon = _route_point(progress, rng)
            timestamp = session_start + timedelta(seconds=int(progress * 900))
            confidence = round(rng.uniform(0.42, 0.97), 3)
            frame_count = rng.randint(settings.min_track_frames, 25)

            sev = estimate_severity(SeverityInputs(
                box_width=rng.uniform(20, 300), box_height=rng.uniform(20, 200),
                frame_width=960, frame_height=540, frame_count=frame_count, mean_confidence=confidence,
            ))

            with SessionLocal() as db:
                nearby = crud.find_nearby_detections(
                    db, lat, lon, settings.duplicate_distance_meters, settings.duplicate_time_window_hours,
                    reference_time=timestamp,
                )
                dup = classify_duplicate(nearby, settings.duplicate_distance_meters)

                pothole_id = format_pothole_id(crud.next_pothole_sequence(db))
                loc = location_engine.resolve(lat, lon)

                evidence = _fake_evidence(pothole_id, timestamp, sample_images, rng, sev.severity) if sample_images else None

                crud.create_detection(
                    db,
                    pothole_id=pothole_id, track_id=d + 1, session_id=session_id,
                    timestamp=timestamp.isoformat(), latitude=lat, longitude=lon,
                    gps_accuracy=round(rng.uniform(3, 15), 1), speed=round(rng.uniform(5, 15), 1),
                    bearing=round(rng.uniform(0, 360), 1), gps_sync_method="interpolated",
                    confidence=confidence, frame_count=frame_count, severity=sev.severity.value,
                    city=loc.city, state=loc.state, zone=loc.zone, ward=loc.ward, locality=loc.locality,
                    postcode=loc.postcode, formatted_address=loc.formatted_address,
                    image_path=str(evidence.original) if evidence else "",
                    annotated_image_path=str(evidence.annotated) if evidence else "",
                    crop_image_path=str(evidence.crop) if evidence else "",
                    duplicate_status=dup.status.value, duplicate_of=dup.duplicate_of,
                    is_demo=True,
                )
                db.commit()
            total_detections += 1

        with SessionLocal() as db:
            crud.finalize_session(db, session_id, session_start + timedelta(seconds=900),
                                   distance_km=dist.total_distance_km, duration_seconds=900,
                                   total_detections=n_detections)
            db.commit()

        logger.info("Demo session %s: %d detections, %.2f km", session_id, n_detections, dist.total_distance_km)

    logger.info("Generated %d demo sessions, %d demo detections total [ALL FLAGGED is_demo=True]", sessions, total_detections)
    return total_detections


def main() -> int:
    parser = argparse.ArgumentParser(description="Populate the database with simulated Bengaluru pothole data for dashboard demonstration")
    parser.add_argument("--sessions", type=int, default=8)
    parser.add_argument("--min-per-session", type=int, default=6)
    parser.add_argument("--max-per-session", type=int, default=16)
    parser.add_argument("--no-geocode", action="store_true", help="Skip real reverse geocoding (faster, offline-safe)")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    generate(args.sessions, args.min_per_session, args.max_per_session, geocode=not args.no_geocode, seed=args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
