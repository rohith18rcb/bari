"""
gps_sync.py — synchronizes video-frame timestamps with a GPS track.

A road video and a GPS log are two independently-sampled time series. This
module aligns them: given an arbitrary (video-derived) timestamp, it finds
the best-estimate GPS fix at that instant using nearest-neighbor lookup or
linear interpolation between bracketing samples — never by naively grabbing
the first GPS row.

Design goals (see project spec):
- support nearest-timestamp and interpolated lookups
- tolerate missing GPS samples (gaps) without crashing
- flag poor GPS accuracy instead of silently trusting it
- support a configurable clock offset between the video and GPS clocks
"""
from __future__ import annotations

import bisect
import csv
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import List, Optional
from zoneinfo import ZoneInfo

from core.geo_utils import circular_mean_bearing

logger = logging.getLogger("bari.gps_sync")

IST = ZoneInfo("Asia/Kolkata")


class SyncMethod(str, Enum):
    EXACT = "exact"
    INTERPOLATED = "interpolated"
    NEAREST = "nearest"
    NEAREST_STALE = "nearest_stale"  # nearest sample, but gap exceeds max_gap_seconds
    EXTRAPOLATED_EDGE = "extrapolated_edge"  # query is before first / after last sample


@dataclass(frozen=True)
class GPSPoint:
    timestamp: datetime
    latitude: float
    longitude: float
    accuracy: float = 0.0
    speed: float = 0.0
    bearing: float = 0.0

    def __post_init__(self):
        if self.timestamp.tzinfo is None:
            raise ValueError("GPSPoint.timestamp must be timezone-aware")
        if not (-90.0 <= self.latitude <= 90.0):
            raise ValueError(f"latitude out of range: {self.latitude}")
        if not (-180.0 <= self.longitude <= 180.0):
            raise ValueError(f"longitude out of range: {self.longitude}")


@dataclass(frozen=True)
class SyncedGPS:
    latitude: float
    longitude: float
    accuracy: float
    speed: float
    bearing: float
    timestamp: datetime
    method: SyncMethod
    gap_seconds: float
    is_low_accuracy: bool


def parse_gps_csv(path: Path | str) -> List[GPSPoint]:
    """Load and validate a GPS track CSV.

    Expected columns: timestamp,latitude,longitude,accuracy,speed,bearing
    ``timestamp`` must be ISO 8601. Naive timestamps are assumed to be in
    Asia/Kolkata (the project's operating timezone).
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"GPS file not found: {path}")

    points: List[GPSPoint] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"timestamp", "latitude", "longitude"}
        if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
            raise ValueError(f"GPS CSV missing required columns {required}, got {reader.fieldnames}")

        for i, row in enumerate(reader):
            try:
                ts = _parse_timestamp(row["timestamp"])
                point = GPSPoint(
                    timestamp=ts,
                    latitude=float(row["latitude"]),
                    longitude=float(row["longitude"]),
                    accuracy=float(row.get("accuracy") or 0.0),
                    speed=float(row.get("speed") or 0.0),
                    bearing=float(row.get("bearing") or 0.0),
                )
                points.append(point)
            except (ValueError, KeyError) as e:
                logger.warning("Skipping malformed GPS row %d: %s", i, e)

    if not points:
        raise ValueError(f"No valid GPS points parsed from {path}")

    points.sort(key=lambda p: p.timestamp)
    return points


def _parse_timestamp(raw: str) -> datetime:
    raw = raw.strip()
    ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=IST)
    return ts


class GPSSynchronizer:
    """Aligns arbitrary query timestamps against a loaded GPS track."""

    def __init__(
        self,
        points: List[GPSPoint],
        interpolate: bool = True,
        max_gap_seconds: float = 5.0,
        time_offset_seconds: float = 0.0,
        min_accuracy_meters: float = 50.0,
    ):
        if not points:
            raise ValueError("GPSSynchronizer requires at least one GPS point")
        self.points = sorted(points, key=lambda p: p.timestamp)
        self._timestamps = [p.timestamp for p in self.points]
        self.interpolate = interpolate
        self.max_gap_seconds = max_gap_seconds
        self.time_offset = timedelta(seconds=time_offset_seconds)
        self.min_accuracy_meters = min_accuracy_meters

    @classmethod
    def from_csv(
        cls,
        path: Path | str,
        interpolate: bool = True,
        max_gap_seconds: float = 5.0,
        time_offset_seconds: float = 0.0,
        min_accuracy_meters: float = 50.0,
    ) -> "GPSSynchronizer":
        points = parse_gps_csv(path)
        return cls(
            points,
            interpolate=interpolate,
            max_gap_seconds=max_gap_seconds,
            time_offset_seconds=time_offset_seconds,
            min_accuracy_meters=min_accuracy_meters,
        )

    @property
    def start_time(self) -> datetime:
        return self.points[0].timestamp

    @property
    def end_time(self) -> datetime:
        return self.points[-1].timestamp

    def get_position_at(self, timestamp: datetime) -> SyncedGPS:
        """Return the best-estimate GPS fix for ``timestamp``."""
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=IST)
        query = timestamp + self.time_offset

        idx = bisect.bisect_left(self._timestamps, query)

        # Exact or near-exact match
        if idx < len(self.points) and self._timestamps[idx] == query:
            return self._to_synced(self.points[idx], query, SyncMethod.EXACT, 0.0)

        # Before the first sample or after the last: hold the edge value
        if idx == 0:
            return self._to_synced(
                self.points[0], query, SyncMethod.EXTRAPOLATED_EDGE,
                abs((self.points[0].timestamp - query).total_seconds()),
            )
        if idx >= len(self.points):
            return self._to_synced(
                self.points[-1], query, SyncMethod.EXTRAPOLATED_EDGE,
                abs((query - self.points[-1].timestamp).total_seconds()),
            )

        before, after = self.points[idx - 1], self.points[idx]
        gap = (after.timestamp - before.timestamp).total_seconds()

        if gap > self.max_gap_seconds:
            # GPS dropout: fall back to whichever bracketing sample is closer,
            # but flag it so downstream consumers know the fix may be stale.
            nearest = before if (query - before.timestamp) <= (after.timestamp - query) else after
            gap_from_query = min(
                abs((query - before.timestamp).total_seconds()),
                abs((after.timestamp - query).total_seconds()),
            )
            return self._to_synced(nearest, query, SyncMethod.NEAREST_STALE, gap_from_query)

        if not self.interpolate:
            nearest = before if (query - before.timestamp) <= (after.timestamp - query) else after
            gap_from_query = min(
                abs((query - before.timestamp).total_seconds()),
                abs((after.timestamp - query).total_seconds()),
            )
            return self._to_synced(nearest, query, SyncMethod.NEAREST, gap_from_query)

        weight = (query - before.timestamp).total_seconds() / gap
        lat = before.latitude + (after.latitude - before.latitude) * weight
        lon = before.longitude + (after.longitude - before.longitude) * weight
        accuracy = max(before.accuracy, after.accuracy)  # conservative: worst-case accuracy
        speed = before.speed + (after.speed - before.speed) * weight
        bearing = circular_mean_bearing(before.bearing, after.bearing, weight)

        synced = SyncedGPS(
            latitude=lat,
            longitude=lon,
            accuracy=accuracy,
            speed=speed,
            bearing=bearing,
            timestamp=query,
            method=SyncMethod.INTERPOLATED,
            gap_seconds=gap,
            is_low_accuracy=accuracy > self.min_accuracy_meters,
        )
        return synced

    def _to_synced(self, point: GPSPoint, query_ts: datetime, method: SyncMethod, gap_seconds: float) -> SyncedGPS:
        return SyncedGPS(
            latitude=point.latitude,
            longitude=point.longitude,
            accuracy=point.accuracy,
            speed=point.speed,
            bearing=point.bearing,
            timestamp=query_ts,
            method=method,
            gap_seconds=gap_seconds,
            is_low_accuracy=point.accuracy > self.min_accuracy_meters,
        )

    def frame_timestamp(self, video_start_time: datetime, frame_index: int, fps: float) -> datetime:
        """Compute the wall-clock timestamp of a given video frame index."""
        return video_start_time + timedelta(seconds=frame_index / fps)
