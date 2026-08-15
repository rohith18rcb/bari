"""
main.py — BARI end-to-end video + GPS pothole detection pipeline.

    VIDEO + GPS CSV -> YOLO -> ByteTrack -> Pothole Event Engine
        -> GPS sync -> Location Engine -> Severity -> Duplicate check
        -> Evidence images -> Database -> Annotated video

Usage:
    python main.py --video data/input/ride01.mp4 --gps data/input/ride01.csv
    python main.py --video data/input/demo.mp4 --gps data/input/demo.csv --demo
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import cv2

from core.config import settings
from core.device import resolve_device
from core.duplicate import classify as classify_duplicate
from core.evidence import save_evidence
from core.events import PotholeEventEngine
from core.geo_utils import filter_and_sum_distance
from core.gps_sync import GPSSynchronizer, SyncedGPS, parse_gps_csv
from core.ids import format_pothole_id, generate_session_id
from core.location import LocationEngine, LocationInfo
from core.overlay import BannerInfo, draw_banner, draw_box
from core.severity import SeverityInputs, SeverityResult, estimate_severity
from core.tracking import track_video
from core.validation import ValidationError, validate_gps_points, validate_video
from db import crud
from db.database import SessionLocal, init_db
from db.crud import PersistentGeocodeCache
from db.database import get_session as db_session_ctx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("bari.main")

IST = ZoneInfo("Asia/Kolkata")
BANNER_DURATION_FRAMES = 20  # how long the confirmation banner stays on screen


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BARI: video + GPS pothole detection pipeline")
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--gps", type=Path, required=True)
    parser.add_argument("--weights", type=Path, default=settings.model_path)
    parser.add_argument("--video-start-time", type=str, default=None,
                         help="ISO8601 wall-clock time of video frame 0. Defaults to the GPS track's first timestamp.")
    parser.add_argument("--output", type=Path, default=None, help="Annotated output video path")
    parser.add_argument("--session-id", type=str, default=None)
    parser.add_argument("--demo", action="store_true", help="Mark this session's records as demo data")
    parser.add_argument("--device", type=str, default=settings.device)
    parser.add_argument("--conf", type=float, default=settings.confidence_threshold)
    parser.add_argument("--iou", type=float, default=settings.iou_threshold)
    parser.add_argument("--no-geocode", action="store_true", help="Skip reverse geocoding (offline / rate-limit safe demo runs)")
    parser.add_argument("--max-frames", type=int, default=None, help="Process at most N frames (quick smoke test)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        video_info = validate_video(args.video)
    except ValidationError as e:
        logger.error("Video validation failed: %s", e)
        return 1
    logger.info("Video loaded: %s (%.1fs, %dx%d @ %.1f fps, %d frames)",
                args.video.name, video_info.duration_seconds, video_info.width, video_info.height,
                video_info.fps, video_info.frame_count)

    try:
        gps_points = parse_gps_csv(args.gps)
        gps_report = validate_gps_points(gps_points, settings.gps_min_accuracy_meters)
    except (ValidationError, FileNotFoundError, ValueError) as e:
        logger.error("GPS validation failed: %s", e)
        return 1
    for issue in gps_report.issues:
        logger.warning("GPS: %s", issue)
    logger.info("GPS track loaded: %d points (%s -> %s)", gps_report.num_points, gps_report.start_time, gps_report.end_time)

    synchronizer = GPSSynchronizer(
        gps_points,
        interpolate=settings.gps_interpolation,
        max_gap_seconds=settings.gps_max_gap_seconds,
        time_offset_seconds=settings.gps_time_offset_seconds,
        min_accuracy_meters=settings.gps_min_accuracy_meters,
    )
    logger.info("GPS synchronization initialized (interpolation=%s, max_gap=%.1fs)",
                settings.gps_interpolation, settings.gps_max_gap_seconds)

    if args.video_start_time:
        video_start_time = datetime.fromisoformat(args.video_start_time)
        if video_start_time.tzinfo is None:
            video_start_time = video_start_time.replace(tzinfo=IST)
    else:
        video_start_time = synchronizer.start_time
        logger.info("No --video-start-time given; assuming video frame 0 aligns with GPS track start (%s)", video_start_time)

    if not args.weights.exists():
        logger.error("Model weights not found: %s. Train a model first (ml/training/train.py).", args.weights)
        return 1

    from ultralytics import YOLO
    device = resolve_device(args.device)
    logger.info("Loading model: %s (device=%s)", args.weights, device)
    model = YOLO(str(args.weights))
    logger.info("Tracking initialized (tracker=%s, min_track_frames=%d)", settings.tracker, settings.min_track_frames)

    init_db()
    session_id = args.session_id or generate_session_id(video_start_time)
    location_engine = LocationEngine(
        cache=None if args.no_geocode else PersistentGeocodeCache(db_session_ctx),
        geocode_enabled=not args.no_geocode,
    )

    output_path = args.output or (settings.output_path / f"{session_id}_annotated.mp4")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(output_path), cv2.VideoWriter_fourcc(*"mp4v"), video_info.fps, (video_info.width, video_info.height))

    with SessionLocal() as db:
        crud.create_session(db, session_id, video_start_time, str(args.video), str(args.gps), is_demo=args.demo)
        db.commit()

    engine = PotholeEventEngine()
    frame_buffer: deque[tuple[int, "np.ndarray"]] = deque(maxlen=max(BANNER_DURATION_FRAMES, settings.min_track_frames + 5, 30))
    active_banners: dict[int, tuple[BannerInfo, int]] = {}
    confirmed_count = 0
    t_start = time.perf_counter()
    last_frame_index = -1

    for ft in track_video(model, str(args.video), conf=args.conf, iou=args.iou, device=device):
        if args.max_frames is not None and ft.frame_index >= args.max_frames:
            break
        last_frame_index = ft.frame_index
        frame_buffer.append((ft.frame_index, ft.frame.copy()))
        annotated = ft.frame.copy()

        for track_id, box, conf in zip(ft.track_ids, ft.boxes_xyxy, ft.confidences):
            draw_box(annotated, box, f"POTHOLE {conf * 100:.0f}%")
            confirmed = engine.update(track_id, ft.frame_index, conf, box)
            if confirmed is not None:
                result = _confirm_event(
                    confirmed, session_id, video_start_time, video_info, synchronizer,
                    location_engine, frame_buffer, args,
                )
                if result is not None:
                    confirmed_count += 1
                    location_label = result.location.locality if result.location.locality != "Unknown" else result.location.city
                    active_banners[track_id] = (
                        BannerInfo(
                            confidence=confirmed.mean_confidence,
                            location=location_label,
                            latitude=result.gps.latitude, longitude=result.gps.longitude,
                            severity=result.severity.severity.value, time_str=result.timestamp.strftime("%H:%M:%S"),
                        ),
                        BANNER_DURATION_FRAMES,
                    )

        expired = []
        for tid, (banner, remaining) in active_banners.items():
            draw_banner(annotated, banner)
            remaining -= 1
            if remaining <= 0:
                expired.append(tid)
            else:
                active_banners[tid] = (banner, remaining)
        for tid in expired:
            del active_banners[tid]

        writer.write(annotated)

        if ft.frame_index % 100 == 0:
            logger.info("Processed frame %d/%d", ft.frame_index, video_info.frame_count)

    writer.release()
    elapsed = time.perf_counter() - t_start
    processed_frames = last_frame_index + 1
    fps_processed = processed_frames / elapsed if elapsed > 0 else 0.0

    points_for_distance = [(p.latitude, p.longitude) for p in gps_points]
    intervals = [(gps_points[i + 1].timestamp - gps_points[i].timestamp).total_seconds() for i in range(len(gps_points) - 1)]
    dist_result = filter_and_sum_distance(points_for_distance, intervals_seconds=intervals)

    with SessionLocal() as db:
        crud.finalize_session(
            db, session_id,
            end_time=video_start_time + timedelta(seconds=processed_frames / video_info.fps),
            distance_km=dist_result.total_distance_km,
            duration_seconds=processed_frames / video_info.fps,
            total_detections=confirmed_count,
        )
        db.commit()

    logger.info("Session %s complete: %d confirmed pothole event(s), %.2f km surveyed, %d frames in %.1fs (%.1f FPS)",
                session_id, confirmed_count, dist_result.total_distance_km, processed_frames, elapsed, fps_processed)
    logger.info("Annotated video: %s", output_path)
    return 0


@dataclass(frozen=True)
class EventConfirmation:
    pothole_id: str
    timestamp: datetime
    gps: SyncedGPS
    location: LocationInfo
    severity: SeverityResult


def _confirm_event(confirmed, session_id, video_start_time, video_info, synchronizer, location_engine, frame_buffer, args) -> EventConfirmation | None:
    """Resolves GPS/location/severity/duplicate status for a newly confirmed
    track, saves evidence images, and writes the DB record. Returns the
    resolved event info, or None if the representative frame could not be
    recovered from the rolling buffer (should not normally happen)."""
    frame_map = dict(frame_buffer)
    raw_frame = frame_map.get(confirmed.representative_frame_index)
    if raw_frame is None:
        logger.warning("Representative frame %d for track %d fell out of buffer; skipping evidence save",
                        confirmed.representative_frame_index, confirmed.track_id)
        return None

    timestamp = video_start_time + timedelta(seconds=confirmed.representative_frame_index / video_info.fps)
    gps = synchronizer.get_position_at(timestamp)
    if gps.is_low_accuracy:
        logger.warning("Low-accuracy GPS fix (%.1fm) for track %d", gps.accuracy, confirmed.track_id)

    loc = location_engine.resolve(gps.latitude, gps.longitude)

    severity = estimate_severity(SeverityInputs(
        box_width=confirmed.representative_box_xyxy[2] - confirmed.representative_box_xyxy[0],
        box_height=confirmed.representative_box_xyxy[3] - confirmed.representative_box_xyxy[1],
        frame_width=video_info.width, frame_height=video_info.height,
        frame_count=confirmed.frame_count, mean_confidence=confirmed.mean_confidence,
    ))

    annotated_frame = raw_frame.copy()
    draw_box(annotated_frame, confirmed.representative_box_xyxy, f"POTHOLE {confirmed.mean_confidence * 100:.0f}%")

    with SessionLocal() as db:
        nearby = crud.find_nearby_detections(
            db, gps.latitude, gps.longitude, settings.duplicate_distance_meters,
            settings.duplicate_time_window_hours, reference_time=timestamp,
        )
        dup = classify_duplicate(nearby, settings.duplicate_distance_meters)

        pothole_id = format_pothole_id(crud.next_pothole_sequence(db))
        evidence = save_evidence(pothole_id, timestamp, raw_frame, annotated_frame, confirmed.representative_box_xyxy)

        crud.create_detection(
            db,
            pothole_id=pothole_id, track_id=confirmed.track_id, session_id=session_id,
            timestamp=timestamp.isoformat(), latitude=gps.latitude, longitude=gps.longitude,
            gps_accuracy=gps.accuracy, speed=gps.speed, bearing=gps.bearing, gps_sync_method=gps.method.value,
            confidence=confirmed.mean_confidence, frame_count=confirmed.frame_count, severity=severity.severity.value,
            city=loc.city, state=loc.state, zone=loc.zone, ward=loc.ward, locality=loc.locality,
            postcode=loc.postcode, formatted_address=loc.formatted_address,
            image_path=str(evidence.original), annotated_image_path=str(evidence.annotated), crop_image_path=str(evidence.crop),
            duplicate_status=dup.status.value, duplicate_of=dup.duplicate_of,
            is_demo=args.demo,
        )
        db.commit()

    logger.info("Pothole confirmed: %s (track=%d, conf=%.2f, severity=%s, dup=%s, ward=%s)",
                pothole_id, confirmed.track_id, confirmed.mean_confidence, severity.severity.value, dup.status.value, loc.ward)
    return EventConfirmation(pothole_id=pothole_id, timestamp=timestamp, gps=gps, location=loc, severity=severity)


if __name__ == "__main__":
    sys.exit(main())
