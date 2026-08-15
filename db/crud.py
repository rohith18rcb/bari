"""Data-access functions for BARI's SQLite database."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DBSession

from core.geo_utils import haversine_distance_meters
from core.geocoding import GeocodeResult
from db.models import Detection, LocationCache, SessionRecord

# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def create_session(
    db: DBSession,
    session_id: str,
    start_time: datetime,
    video_source: str,
    gps_source: str,
    is_demo: bool = False,
) -> SessionRecord:
    record = SessionRecord(
        session_id=session_id,
        start_time=start_time.isoformat(),
        video_source=video_source,
        gps_source=gps_source,
        is_demo=is_demo,
    )
    db.add(record)
    db.flush()
    return record


def finalize_session(
    db: DBSession,
    session_id: str,
    end_time: datetime,
    distance_km: float,
    duration_seconds: float,
    total_detections: int,
) -> None:
    record = db.get(SessionRecord, session_id)
    if record is None:
        raise ValueError(f"Unknown session_id: {session_id}")
    record.end_time = end_time.isoformat()
    record.distance_km = distance_km
    record.duration_seconds = duration_seconds
    record.total_detections = total_detections


def list_sessions(db: DBSession) -> list[SessionRecord]:
    return list(db.execute(select(SessionRecord).order_by(SessionRecord.start_time.desc())).scalars())


# ---------------------------------------------------------------------------
# Detections
# ---------------------------------------------------------------------------

def next_pothole_sequence(db: DBSession) -> int:
    count = db.execute(select(func.count()).select_from(Detection)).scalar_one()
    return int(count) + 1


def create_detection(db: DBSession, **fields) -> Detection:
    record = Detection(**fields)
    db.add(record)
    db.flush()
    return record


def find_nearby_detections(
    db: DBSession,
    latitude: float,
    longitude: float,
    max_distance_meters: float,
    time_window_hours: float,
    reference_time: Optional[datetime] = None,
    exclude_pothole_id: Optional[str] = None,
) -> list[tuple[Detection, float]]:
    """Level-2 duplicate check: find previously confirmed potholes within
    ``max_distance_meters`` and ``time_window_hours`` of a new detection.

    Uses a coarse lat/lon bounding-box pre-filter (cheap, index-friendly)
    followed by exact Haversine distance filtering in Python, since SQLite
    has no native geospatial functions.
    """
    reference_time = reference_time or datetime.now(timezone.utc)
    # ~1 degree latitude ~= 111km; pad generously then filter exactly.
    deg_pad = max(max_distance_meters / 111_000.0, 0.0005) * 3
    min_lat, max_lat = latitude - deg_pad, latitude + deg_pad
    min_lon, max_lon = longitude - deg_pad, longitude + deg_pad

    cutoff = (reference_time - timedelta(hours=time_window_hours)).isoformat()

    stmt = select(Detection).where(
        Detection.latitude.between(min_lat, max_lat),
        Detection.longitude.between(min_lon, max_lon),
        Detection.timestamp >= cutoff,
    )
    if exclude_pothole_id:
        stmt = stmt.where(Detection.pothole_id != exclude_pothole_id)

    candidates = db.execute(stmt).scalars().all()
    results = []
    for c in candidates:
        d = haversine_distance_meters(latitude, longitude, c.latitude, c.longitude)
        if d <= max_distance_meters:
            results.append((c, d))
    results.sort(key=lambda t: t[1])
    return results


def list_detections(
    db: DBSession,
    zone: Optional[str] = None,
    ward: Optional[str] = None,
    locality: Optional[str] = None,
    severity: Optional[str] = None,
    session_id: Optional[str] = None,
    min_confidence: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 5000,
) -> list[Detection]:
    stmt = select(Detection).order_by(Detection.timestamp.desc())
    if zone:
        stmt = stmt.where(Detection.zone == zone)
    if ward:
        stmt = stmt.where(Detection.ward == ward)
    if locality:
        stmt = stmt.where(Detection.locality == locality)
    if severity:
        stmt = stmt.where(Detection.severity == severity)
    if session_id:
        stmt = stmt.where(Detection.session_id == session_id)
    if min_confidence is not None:
        stmt = stmt.where(Detection.confidence >= min_confidence)
    if start_date:
        stmt = stmt.where(Detection.timestamp >= start_date)
    if end_date:
        stmt = stmt.where(Detection.timestamp <= end_date)
    stmt = stmt.limit(limit)
    return list(db.execute(stmt).scalars())


def get_detection(db: DBSession, pothole_id: str) -> Optional[Detection]:
    return db.execute(select(Detection).where(Detection.pothole_id == pothole_id)).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def get_stats(db: DBSession) -> dict:
    total = db.execute(select(func.count()).select_from(Detection)).scalar_one()

    by_severity = dict(
        db.execute(select(Detection.severity, func.count()).group_by(Detection.severity)).all()
    )

    now = datetime.now().astimezone()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    week_start = (now - timedelta(days=7)).isoformat()

    today_count = db.execute(
        select(func.count()).select_from(Detection).where(Detection.timestamp >= today_start)
    ).scalar_one()
    week_count = db.execute(
        select(func.count()).select_from(Detection).where(Detection.timestamp >= week_start)
    ).scalar_one()

    total_distance = db.execute(select(func.coalesce(func.sum(SessionRecord.distance_km), 0.0))).scalar_one()
    session_count = db.execute(select(func.count()).select_from(SessionRecord)).scalar_one()

    def top_of(column) -> Optional[str]:
        row = db.execute(
            select(column, func.count().label("c"))
            .where(column != "Unknown")
            .group_by(column)
            .order_by(func.count().desc())
            .limit(1)
        ).first()
        return row[0] if row else None

    return {
        "total_potholes": total,
        "high_severity": by_severity.get("HIGH", 0),
        "medium_severity": by_severity.get("MEDIUM", 0),
        "low_severity": by_severity.get("LOW", 0),
        "today": today_count,
        "this_week": week_count,
        "total_distance_km": round(total_distance, 2),
        "total_sessions": session_count,
        "most_affected_zone": top_of(Detection.zone),
        "most_affected_ward": top_of(Detection.ward),
        "most_affected_locality": top_of(Detection.locality),
    }


def get_analytics(db: DBSession) -> dict:
    def group_count(column) -> list[dict]:
        rows = db.execute(
            select(column, func.count()).where(column != "Unknown").group_by(column).order_by(func.count().desc())
        ).all()
        return [{"label": r[0], "count": r[1]} for r in rows]

    by_date = db.execute(
        select(func.substr(Detection.timestamp, 1, 10), func.count())
        .group_by(func.substr(Detection.timestamp, 1, 10))
        .order_by(func.substr(Detection.timestamp, 1, 10))
    ).all()

    return {
        "by_zone": group_count(Detection.zone),
        "by_ward": group_count(Detection.ward),
        "by_locality": group_count(Detection.locality),
        "by_severity": group_count(Detection.severity),
        "over_time": [{"date": r[0], "count": r[1]} for r in by_date],
    }


# ---------------------------------------------------------------------------
# Persistent reverse-geocode cache (backs core.geocoding.GeocodeCache)
# ---------------------------------------------------------------------------

class PersistentGeocodeCache:
    """Adapts the `location_cache` table to the GeocodeCache protocol."""

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def get(self, key: str) -> Optional[GeocodeResult]:
        with self._session_factory() as db:
            row = db.get(LocationCache, key)
            if row is None:
                return None
            return GeocodeResult(
                city=row.city, state=row.state, postcode=row.postcode, locality=row.locality,
                formatted_address=row.formatted_address, success=row.success, provider="nominatim",
            )

    def set(self, key: str, value: GeocodeResult) -> None:
        with self._session_factory() as db:
            row = db.get(LocationCache, key)
            if row is None:
                row = LocationCache(cache_key=key)
                db.add(row)
            row.city = value.city
            row.state = value.state
            row.postcode = value.postcode
            row.locality = value.locality
            row.formatted_address = value.formatted_address
            row.success = value.success
            db.commit()
