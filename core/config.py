"""
Central configuration for BARI, loaded from environment variables / .env.

All tunable thresholds live here so behavior can be changed without touching
code (see .env.example for the full list of variables).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    val = os.getenv(name)
    return float(val) if val not in (None, "") else default


def _int(name: str, default: int) -> int:
    val = os.getenv(name)
    return int(val) if val not in (None, "") else default


def _path(name: str, default: str) -> Path:
    val = os.getenv(name, default)
    p = Path(val)
    return p if p.is_absolute() else (PROJECT_ROOT / p)


@dataclass(frozen=True)
class Settings:
    project_root: Path = PROJECT_ROOT

    # Model
    model_path: Path = field(default_factory=lambda: _path("MODEL_PATH", "ml/training/runs/pothole_yolo/weights/best.pt"))
    confidence_threshold: float = field(default_factory=lambda: _float("CONFIDENCE_THRESHOLD", 0.35))
    iou_threshold: float = field(default_factory=lambda: _float("IOU_THRESHOLD", 0.45))
    device: str = field(default_factory=lambda: os.getenv("DEVICE", "auto"))
    img_size: int = field(default_factory=lambda: _int("IMG_SIZE", 640))

    # Tracking
    tracker: str = field(default_factory=lambda: os.getenv("TRACKER", "bytetrack.yaml"))
    min_track_frames: int = field(default_factory=lambda: _int("MIN_TRACK_FRAMES", 3))

    # Duplicate detection
    duplicate_distance_meters: float = field(default_factory=lambda: _float("DUPLICATE_DISTANCE_METERS", 8.0))
    duplicate_time_window_hours: float = field(default_factory=lambda: _float("DUPLICATE_TIME_WINDOW_HOURS", 720.0))

    # GPS sync
    gps_interpolation: bool = field(default_factory=lambda: _bool("GPS_INTERPOLATION", True))
    gps_max_gap_seconds: float = field(default_factory=lambda: _float("GPS_MAX_GAP_SECONDS", 5.0))
    gps_time_offset_seconds: float = field(default_factory=lambda: _float("GPS_TIME_OFFSET_SECONDS", 0.0))
    gps_min_accuracy_meters: float = field(default_factory=lambda: _float("GPS_MIN_ACCURACY_METERS", 50.0))

    # Severity
    severity_area_low: float = field(default_factory=lambda: _float("SEVERITY_AREA_LOW", 0.015))
    severity_area_high: float = field(default_factory=lambda: _float("SEVERITY_AREA_HIGH", 0.05))

    # Geocoding
    geocoder_provider: str = field(default_factory=lambda: os.getenv("GEOCODER_PROVIDER", "nominatim"))
    geocoder_user_agent: str = field(default_factory=lambda: os.getenv("GEOCODER_USER_AGENT", "bari-pothole-detector/1.0"))
    geocoder_timeout_seconds: float = field(default_factory=lambda: _float("GEOCODER_TIMEOUT_SECONDS", 10.0))
    geocoder_min_interval_seconds: float = field(default_factory=lambda: _float("GEOCODER_MIN_INTERVAL_SECONDS", 1.0))
    geocoder_max_retries: int = field(default_factory=lambda: _int("GEOCODER_MAX_RETRIES", 3))

    # GIS boundaries
    zone_boundary_geojson: Path = field(default_factory=lambda: _path("ZONE_BOUNDARY_GEOJSON", "data/bengaluru/zones.geojson"))
    ward_boundary_geojson: Path = field(default_factory=lambda: _path("WARD_BOUNDARY_GEOJSON", "data/bengaluru/wards.geojson"))

    # Storage
    database_path: Path = field(default_factory=lambda: _path("DATABASE_PATH", "data/bari.db"))
    evidence_path: Path = field(default_factory=lambda: _path("EVIDENCE_PATH", "data/evidence"))
    output_path: Path = field(default_factory=lambda: _path("OUTPUT_PATH", "data/output"))

    # Timezone
    timezone: str = field(default_factory=lambda: os.getenv("TIMEZONE", "Asia/Kolkata"))

    # Dashboard
    dashboard_host: str = field(default_factory=lambda: os.getenv("DASHBOARD_HOST", "127.0.0.1"))
    dashboard_port: int = field(default_factory=lambda: _int("DASHBOARD_PORT", 8000))


settings = Settings()
