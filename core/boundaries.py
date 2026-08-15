"""
boundaries.py — GeoJSON administrative boundary loading + point-in-polygon
lookup for Bengaluru zones/wards.

Boundary files are optional. If a file is missing, the corresponding lookup
returns "Unknown" rather than raising — the rest of the pipeline (GPS,
reverse geocoding, severity, DB) must keep working without them. See
data/bengaluru/README.md for where real boundary files should be placed.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from shapely.geometry import Point, shape
from shapely.strtree import STRtree

logger = logging.getLogger("bari.boundaries")

UNKNOWN = "Unknown"

_NAME_KEYS = ("name", "KGISWardName", "WardName", "zone", "ZONE_NAME", "Zone_Name", "NAME", "ward", "WARD_NAME")


def _extract_name(properties: dict) -> str:
    for key in _NAME_KEYS:
        val = properties.get(key)
        if val:
            return str(val)
    return UNKNOWN


class BoundaryIndex:
    """Loads one GeoJSON FeatureCollection and supports point-in-polygon lookup."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._geometries: list = []
        self._names: list[str] = []
        self._tree: Optional[STRtree] = None
        self.loaded = False
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            logger.warning("Boundary file not found: %s (lookups will return 'Unknown')", self.path)
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            for feature in data.get("features", []):
                geom = shape(feature["geometry"])
                self._geometries.append(geom)
                self._names.append(_extract_name(feature.get("properties", {})))
            if self._geometries:
                self._tree = STRtree(self._geometries)
            self.loaded = True
            logger.info("Loaded %d boundary polygons from %s", len(self._geometries), self.path)
        except Exception as e:  # noqa: BLE001 - boundary loading must never crash the pipeline
            logger.error("Failed to load boundary file %s: %s", self.path, e)

    def lookup(self, latitude: float, longitude: float) -> str:
        if not self.loaded or self._tree is None:
            return UNKNOWN
        point = Point(longitude, latitude)  # GeoJSON is (lon, lat)
        try:
            candidate_indices = self._tree.query(point)
        except Exception:  # noqa: BLE001
            return UNKNOWN
        for idx in candidate_indices:
            geom = self._geometries[idx]
            if geom.contains(point) or geom.intersects(point):
                return self._names[idx]
        return UNKNOWN


_ward_index: Optional[BoundaryIndex] = None
_zone_index: Optional[BoundaryIndex] = None


def get_ward_index() -> BoundaryIndex:
    global _ward_index
    if _ward_index is None:
        from core.config import settings
        _ward_index = BoundaryIndex(settings.ward_boundary_geojson)
    return _ward_index


def get_zone_index() -> BoundaryIndex:
    global _zone_index
    if _zone_index is None:
        from core.config import settings
        _zone_index = BoundaryIndex(settings.zone_boundary_geojson)
    return _zone_index


def resolve_ward(latitude: float, longitude: float) -> str:
    return get_ward_index().lookup(latitude, longitude)


def resolve_zone(latitude: float, longitude: float) -> str:
    return get_zone_index().lookup(latitude, longitude)
