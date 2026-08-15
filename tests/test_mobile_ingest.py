from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import pytest
import torch

from core.location import LocationEngine
from core.mobile_ingest import GPS_SYNC_METHOD_DEVICE, MOBILE_TRACK_ID, process_mobile_photo
from db import crud

IST = ZoneInfo("Asia/Kolkata")


class FakeBoxes:
    def __init__(self, confs, xyxys):
        self.conf = torch.tensor(confs)
        self.xyxy = torch.tensor(xyxys)

    def __len__(self):
        return len(self.conf)


class FakeModel:
    def __init__(self, confs=None, xyxys=None):
        self._confs = confs or []
        self._xyxys = xyxys or []

    def predict(self, image, conf=None, iou=None, verbose=None):
        boxes = FakeBoxes(self._confs, self._xyxys) if self._confs else None
        return [SimpleNamespace(boxes=boxes)]


@pytest.fixture
def dummy_image():
    return np.zeros((480, 640, 3), dtype=np.uint8)


@pytest.fixture
def location_engine():
    return LocationEngine(geocode_enabled=False)


def _seed_session(db, session_id="SES-MOBILE-TEST"):
    crud.create_session(db, session_id, datetime.now(IST), "[MOBILE] test", "[MOBILE]", is_demo=False)
    db.commit()
    return session_id


def test_no_detection_returns_not_detected(db_session, dummy_image, location_engine, tmp_path, monkeypatch):
    session_id = _seed_session(db_session)
    model = FakeModel()  # no boxes at all

    result = process_mobile_photo(
        db_session, model, session_id, dummy_image, datetime.now(IST),
        12.97, 77.59, 5.0, 5.0, 90.0, location_engine,
    )
    assert result.detected is False
    assert result.pothole_id is None
    assert len(crud.list_detections(db_session)) == 0


def test_detection_creates_record(db_session, dummy_image, location_engine, monkeypatch, tmp_path):
    session_id = _seed_session(db_session)
    model = FakeModel(confs=[0.85], xyxys=[[100, 100, 300, 250]])

    # Evidence saving writes real files; redirect to a temp dir for the test.
    import dataclasses
    import core.evidence as evidence_module
    monkeypatch.setattr(evidence_module, "settings", dataclasses.replace(evidence_module.settings, evidence_path=tmp_path))

    result = process_mobile_photo(
        db_session, model, session_id, dummy_image, datetime.now(IST),
        12.9784, 77.6408, 6.0, 8.0, 90.0, location_engine,
    )
    assert result.detected is True
    assert result.pothole_id is not None
    assert result.confidence == pytest.approx(0.85)

    saved = crud.get_detection(db_session, result.pothole_id)
    assert saved is not None
    assert saved.track_id == MOBILE_TRACK_ID
    assert saved.gps_sync_method == GPS_SYNC_METHOD_DEVICE
    assert saved.frame_count == 1
    assert saved.is_demo is False


def test_picks_highest_confidence_box(db_session, dummy_image, location_engine, monkeypatch, tmp_path):
    session_id = _seed_session(db_session)
    model = FakeModel(confs=[0.4, 0.9, 0.6], xyxys=[[0, 0, 50, 50], [100, 100, 400, 300], [200, 200, 250, 250]])

    import dataclasses
    import core.evidence as evidence_module
    monkeypatch.setattr(evidence_module, "settings", dataclasses.replace(evidence_module.settings, evidence_path=tmp_path))

    result = process_mobile_photo(
        db_session, model, session_id, dummy_image, datetime.now(IST),
        12.97, 77.59, 5.0, 5.0, 90.0, location_engine,
    )
    assert result.confidence == pytest.approx(0.9)


def test_second_nearby_detection_flagged_as_duplicate(db_session, dummy_image, location_engine, monkeypatch, tmp_path):
    session_id = _seed_session(db_session)
    model = FakeModel(confs=[0.8], xyxys=[[100, 100, 200, 200]])

    import dataclasses
    import core.evidence as evidence_module
    monkeypatch.setattr(evidence_module, "settings", dataclasses.replace(evidence_module.settings, evidence_path=tmp_path))

    first = process_mobile_photo(db_session, model, session_id, dummy_image, datetime.now(IST), 12.9784, 77.6408, 5.0, 5.0, 90.0, location_engine)
    db_session.commit()
    second = process_mobile_photo(db_session, model, session_id, dummy_image, datetime.now(IST), 12.97841, 77.64081, 5.0, 5.0, 90.0, location_engine)

    assert first.duplicate_status == "NEW"
    assert second.duplicate_status in ("KNOWN", "POSSIBLE_DUPLICATE")
