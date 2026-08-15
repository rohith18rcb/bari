from __future__ import annotations

import pytest

from core.geo_utils import circular_mean_bearing, filter_and_sum_distance, haversine_distance_meters


def test_haversine_zero_distance():
    assert haversine_distance_meters(12.97, 77.59, 12.97, 77.59) == pytest.approx(0.0, abs=1e-6)


def test_haversine_known_one_degree_latitude():
    # 1 degree of latitude is ~111.19 km everywhere on Earth
    d = haversine_distance_meters(0.0, 0.0, 1.0, 0.0)
    assert d == pytest.approx(111_195, rel=0.01)


def test_circular_mean_bearing_interpolates():
    assert circular_mean_bearing(0.0, 90.0, 0.5) == pytest.approx(45.0, abs=0.5)


def test_circular_mean_bearing_wraps_around_north():
    # 350 -> 10 degrees should interpolate through 0/360, not the long way through 180
    mid = circular_mean_bearing(350.0, 10.0, 0.5)
    assert mid == pytest.approx(0.0, abs=1.0) or mid == pytest.approx(360.0, abs=1.0)


def test_filter_and_sum_distance_accepts_normal_movement():
    points = [(12.9716, 77.5946), (12.9720, 77.5950), (12.9724, 77.5954)]
    result = filter_and_sum_distance(points)
    assert result.points_rejected == 0
    assert result.total_distance_km > 0


def test_filter_and_sum_distance_rejects_impossible_jump():
    points = [(12.9716, 77.5946), (13.5, 78.5), (12.9720, 77.5950)]  # middle point is a huge GPS glitch
    intervals = [1.0, 1.0]  # 1 second between each sample -> implied speed is absurd
    result = filter_and_sum_distance(points, intervals_seconds=intervals, max_speed_mps=55.0)
    assert result.points_rejected == 2  # both jumps in/out of the glitch point rejected


def test_filter_and_sum_distance_single_point():
    result = filter_and_sum_distance([(12.97, 77.59)])
    assert result.total_distance_km == 0.0
