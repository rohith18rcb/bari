from __future__ import annotations

import json
from pathlib import Path

from core.boundaries import BoundaryIndex


def _write_square_geojson(path: Path, name: str, coords) -> None:
    geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"name": name},
            "geometry": {"type": "Polygon", "coordinates": [coords]},
        }],
    }
    path.write_text(json.dumps(geojson), encoding="utf-8")


def test_boundary_index_missing_file_returns_unknown(tmp_path: Path):
    idx = BoundaryIndex(tmp_path / "does_not_exist.geojson")
    assert idx.loaded is False
    assert idx.lookup(12.97, 77.59) == "Unknown"


def test_boundary_index_point_inside_polygon(tmp_path: Path):
    path = tmp_path / "test_zone.geojson"
    # A square from (77.0,12.0) to (78.0,13.0) in (lon,lat) GeoJSON order
    _write_square_geojson(path, "TestZone", [[77.0, 12.0], [78.0, 12.0], [78.0, 13.0], [77.0, 13.0], [77.0, 12.0]])
    idx = BoundaryIndex(path)
    assert idx.loaded is True
    assert idx.lookup(12.5, 77.5) == "TestZone"  # inside the square


def test_boundary_index_point_outside_polygon(tmp_path: Path):
    path = tmp_path / "test_zone.geojson"
    _write_square_geojson(path, "TestZone", [[77.0, 12.0], [78.0, 12.0], [78.0, 13.0], [77.0, 13.0], [77.0, 12.0]])
    idx = BoundaryIndex(path)
    assert idx.lookup(50.0, 50.0) == "Unknown"  # nowhere near the square


def test_real_ward_boundaries_load_and_resolve():
    """Uses the actual bundled BBMP ward GeoJSON (data/bengaluru/wards.geojson)."""
    from core.config import settings
    if not settings.ward_boundary_geojson.exists():
        import pytest
        pytest.skip("Real ward boundary file not present in this environment")

    idx = BoundaryIndex(settings.ward_boundary_geojson)
    assert idx.loaded is True
    assert len(idx._geometries) > 100  # 243 wards expected
    # A point clearly outside Bengaluru entirely
    assert idx.lookup(0.0, 0.0) == "Unknown"
