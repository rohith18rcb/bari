"""Reusable geospatial math: Haversine distance, bearing, GPS jump filtering."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

EARTH_RADIUS_M = 6_371_000.0


def haversine_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points, in meters."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def circular_mean_bearing(b1: float, b2: float, weight: float) -> float:
    """Interpolate between two compass bearings (degrees) along the shorter arc.

    weight=0 -> b1, weight=1 -> b2.
    """
    r1, r2 = math.radians(b1), math.radians(b2)
    x = (1 - weight) * math.cos(r1) + weight * math.cos(r2)
    y = (1 - weight) * math.sin(r1) + weight * math.sin(r2)
    result = math.degrees(math.atan2(y, x))
    return result % 360.0


@dataclass
class DistanceFilterResult:
    total_distance_km: float
    points_used: int
    points_rejected: int


def filter_and_sum_distance(
    points: Sequence[tuple[float, float]],
    max_speed_mps: float = 55.0,
    min_interval_check: bool = True,
    intervals_seconds: Sequence[float] | None = None,
) -> DistanceFilterResult:
    """Sum Haversine distance across consecutive points, rejecting physically
    impossible jumps (e.g. GPS glitches) based on an implied speed cap.

    If ``intervals_seconds`` is provided (same length - 1 as points), the
    implied speed between consecutive points is checked against
    ``max_speed_mps`` (default ~198 km/h, generous for noisy consumer GPS).
    Without intervals, a fixed-distance sanity cap of 200m per sample is used.
    """
    if len(points) < 2:
        return DistanceFilterResult(0.0, len(points), 0)

    total_m = 0.0
    used = 1
    rejected = 0
    for i in range(1, len(points)):
        lat1, lon1 = points[i - 1]
        lat2, lon2 = points[i]
        d = haversine_distance_meters(lat1, lon1, lat2, lon2)

        if intervals_seconds is not None and i - 1 < len(intervals_seconds):
            dt = max(intervals_seconds[i - 1], 1e-6)
            implied_speed = d / dt
            if implied_speed > max_speed_mps:
                rejected += 1
                continue
        elif d > 200.0:
            rejected += 1
            continue

        total_m += d
        used += 1

    return DistanceFilterResult(total_distance_km=total_m / 1000.0, points_used=used, points_rejected=rejected)
