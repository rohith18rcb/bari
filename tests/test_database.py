from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from db import crud

IST = ZoneInfo("Asia/Kolkata")


def _make_session(db, session_id="SES-TEST-0001"):
    return crud.create_session(db, session_id, datetime.now(IST), "video.mp4", "gps.csv", is_demo=True)


def _make_detection(db, session_id, pothole_id, lat, lon, timestamp=None, **overrides):
    fields = dict(
        pothole_id=pothole_id, track_id=1, session_id=session_id,
        timestamp=(timestamp or datetime.now(IST)).isoformat(),
        latitude=lat, longitude=lon, gps_accuracy=5.0, speed=5.0, bearing=90.0,
        gps_sync_method="interpolated", confidence=0.8, frame_count=5, severity="MEDIUM",
        city="Bengaluru", state="Karnataka", zone="Unknown", ward="Test Ward", locality="Test Locality",
        postcode="560001", formatted_address="Test Address", is_demo=True,
    )
    fields.update(overrides)
    return crud.create_detection(db, **fields)


def test_create_session_and_finalize(db_session):
    s = _make_session(db_session)
    db_session.commit()
    assert s.session_id == "SES-TEST-0001"

    crud.finalize_session(db_session, s.session_id, datetime.now(IST), distance_km=2.5, duration_seconds=120, total_detections=3)
    db_session.commit()

    fetched = db_session.get(type(s), s.session_id)
    assert fetched.distance_km == 2.5
    assert fetched.total_detections == 3


def test_next_pothole_sequence_increments(db_session):
    _make_session(db_session)
    db_session.commit()
    assert crud.next_pothole_sequence(db_session) == 1
    _make_detection(db_session, "SES-TEST-0001", "PTH-000001", 12.97, 77.59)
    db_session.commit()
    assert crud.next_pothole_sequence(db_session) == 2


def test_find_nearby_detections_distance_filter(db_session):
    _make_session(db_session)
    db_session.commit()
    # ~0 meters away (same point)
    _make_detection(db_session, "SES-TEST-0001", "PTH-000001", 12.9716, 77.5946)
    # far away (different part of Bengaluru, >1km)
    _make_detection(db_session, "SES-TEST-0001", "PTH-000002", 12.99, 77.62)
    db_session.commit()

    nearby = crud.find_nearby_detections(db_session, 12.9716, 77.5946, max_distance_meters=10.0, time_window_hours=24)
    ids = [d.pothole_id for d, _dist in nearby]
    assert "PTH-000001" in ids
    assert "PTH-000002" not in ids


def test_find_nearby_detections_time_window(db_session):
    _make_session(db_session)
    db_session.commit()
    old_time = datetime.now(IST) - timedelta(hours=100)
    _make_detection(db_session, "SES-TEST-0001", "PTH-000001", 12.9716, 77.5946, timestamp=old_time)
    db_session.commit()

    nearby = crud.find_nearby_detections(db_session, 12.9716, 77.5946, max_distance_meters=10.0, time_window_hours=1)
    assert len(nearby) == 0


def test_get_stats_counts_by_severity(db_session):
    _make_session(db_session)
    db_session.commit()
    _make_detection(db_session, "SES-TEST-0001", "PTH-000001", 12.97, 77.59, severity="HIGH")
    _make_detection(db_session, "SES-TEST-0001", "PTH-000002", 12.97, 77.59, severity="LOW")
    db_session.commit()

    stats = crud.get_stats(db_session)
    assert stats["total_potholes"] == 2
    assert stats["high_severity"] == 1
    assert stats["low_severity"] == 1


def test_list_detections_filters_by_severity(db_session):
    _make_session(db_session)
    db_session.commit()
    _make_detection(db_session, "SES-TEST-0001", "PTH-000001", 12.97, 77.59, severity="HIGH")
    _make_detection(db_session, "SES-TEST-0001", "PTH-000002", 12.97, 77.59, severity="LOW")
    db_session.commit()

    high_only = crud.list_detections(db_session, severity="HIGH")
    assert len(high_only) == 1
    assert high_only[0].pothole_id == "PTH-000001"


def test_get_detection_by_id(db_session):
    _make_session(db_session)
    db_session.commit()
    _make_detection(db_session, "SES-TEST-0001", "PTH-000001", 12.97, 77.59)
    db_session.commit()

    d = crud.get_detection(db_session, "PTH-000001")
    assert d is not None
    assert d.latitude == 12.97

    assert crud.get_detection(db_session, "PTH-999999") is None


def test_persistent_geocode_cache_roundtrip(db_session_factory):
    from core.geocoding import GeocodeResult
    from db.crud import PersistentGeocodeCache

    cache = PersistentGeocodeCache(db_session_factory)
    assert cache.get("12.97,77.59") is None

    result = GeocodeResult(city="Bengaluru", state="Karnataka", postcode="560001", locality="MG Road", formatted_address="MG Road, Bengaluru", success=True, provider="nominatim")
    cache.set("12.97,77.59", result)

    fetched = cache.get("12.97,77.59")
    assert fetched is not None
    assert fetched.city == "Bengaluru"
