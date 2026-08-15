from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from core.gps_sync import GPSPoint, GPSSynchronizer, SyncMethod, parse_gps_csv

IST = ZoneInfo("Asia/Kolkata")


def test_gps_point_rejects_naive_timestamp():
    with pytest.raises(ValueError):
        GPSPoint(datetime(2026, 8, 14, 14, 0, 0), 12.97, 77.59)


def test_gps_point_rejects_out_of_range_latlon():
    with pytest.raises(ValueError):
        GPSPoint(datetime(2026, 8, 14, tzinfo=IST), 200.0, 77.59)
    with pytest.raises(ValueError):
        GPSPoint(datetime(2026, 8, 14, tzinfo=IST), 12.97, 200.0)


def test_interpolation_midpoint(sample_gps_points):
    sync = GPSSynchronizer(sample_gps_points, interpolate=True, max_gap_seconds=5.0)
    result = sync.get_position_at(sample_gps_points[0].timestamp + timedelta(seconds=1))
    assert result.method == SyncMethod.INTERPOLATED
    # halfway between point 0 and point 1
    assert result.latitude == pytest.approx((12.9716 + 12.9718) / 2, abs=1e-6)
    assert result.longitude == pytest.approx((77.5946 + 77.5950) / 2, abs=1e-6)


def test_exact_match_returns_exact(sample_gps_points):
    sync = GPSSynchronizer(sample_gps_points)
    result = sync.get_position_at(sample_gps_points[1].timestamp)
    assert result.method == SyncMethod.EXACT
    assert result.latitude == sample_gps_points[1].latitude


def test_gap_exceeding_threshold_is_nearest_stale(sample_gps_points):
    # points[2] -> points[3] gap is 6 seconds; max_gap_seconds=5 should trigger NEAREST_STALE
    sync = GPSSynchronizer(sample_gps_points, interpolate=True, max_gap_seconds=5.0)
    query_time = sample_gps_points[2].timestamp + timedelta(seconds=3)  # roughly midway in the gap
    result = sync.get_position_at(query_time)
    assert result.method == SyncMethod.NEAREST_STALE


def test_query_before_first_point_extrapolates_edge(sample_gps_points):
    sync = GPSSynchronizer(sample_gps_points)
    result = sync.get_position_at(sample_gps_points[0].timestamp - timedelta(seconds=10))
    assert result.method == SyncMethod.EXTRAPOLATED_EDGE
    assert result.latitude == sample_gps_points[0].latitude


def test_query_after_last_point_extrapolates_edge(sample_gps_points):
    sync = GPSSynchronizer(sample_gps_points)
    result = sync.get_position_at(sample_gps_points[-1].timestamp + timedelta(seconds=100))
    assert result.method == SyncMethod.EXTRAPOLATED_EDGE
    assert result.latitude == sample_gps_points[-1].latitude


def test_interpolation_disabled_uses_nearest(sample_gps_points):
    sync = GPSSynchronizer(sample_gps_points, interpolate=False, max_gap_seconds=5.0)
    # query 0.4s after point 0 (closer to point 0 than point 1, which is 2s away)
    result = sync.get_position_at(sample_gps_points[0].timestamp + timedelta(seconds=0.4))
    assert result.method == SyncMethod.NEAREST
    assert result.latitude == sample_gps_points[0].latitude


def test_time_offset_shifts_query(sample_gps_points):
    # Without offset, exact match at point[1].timestamp; with a -2s offset applied to the
    # query, we need to query 2s later for the same exact-match result.
    sync = GPSSynchronizer(sample_gps_points, time_offset_seconds=-2.0)
    result = sync.get_position_at(sample_gps_points[1].timestamp + timedelta(seconds=2))
    assert result.method == SyncMethod.EXACT
    assert result.latitude == sample_gps_points[1].latitude


def test_low_accuracy_flagged(sample_gps_points):
    sync = GPSSynchronizer(sample_gps_points, min_accuracy_meters=1.0)  # all points exceed this
    result = sync.get_position_at(sample_gps_points[0].timestamp)
    assert result.is_low_accuracy is True


def test_parse_gps_csv_valid(tmp_path: Path):
    csv_path = tmp_path / "gps.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "latitude", "longitude", "accuracy", "speed", "bearing"])
        writer.writerow(["2026-08-14T14:00:00+05:30", "12.9716", "77.5946", "5.0", "0", "90"])
        writer.writerow(["2026-08-14T14:00:01+05:30", "12.9717", "77.5948", "5.0", "4.2", "91"])
    points = parse_gps_csv(csv_path)
    assert len(points) == 2
    assert points[0].timestamp.tzinfo is not None


def test_parse_gps_csv_skips_malformed_rows(tmp_path: Path):
    csv_path = tmp_path / "gps.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "latitude", "longitude", "accuracy", "speed", "bearing"])
        writer.writerow(["2026-08-14T14:00:00+05:30", "12.9716", "77.5946", "5.0", "0", "90"])
        writer.writerow(["not-a-timestamp", "bad", "row", "", "", ""])
    points = parse_gps_csv(csv_path)
    assert len(points) == 1


def test_parse_gps_csv_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        parse_gps_csv(tmp_path / "does_not_exist.csv")


def test_parse_gps_csv_missing_columns_raises(tmp_path: Path):
    csv_path = tmp_path / "gps.csv"
    csv_path.write_text("foo,bar\n1,2\n")
    with pytest.raises(ValueError):
        parse_gps_csv(csv_path)
