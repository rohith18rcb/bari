from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db.models import Base
from core.gps_sync import GPSPoint

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def db_session_factory():
    """A fresh in-memory SQLite database per test, isolated from the real project DB."""
    # StaticPool + a single shared connection so the in-memory DB survives
    # across threads (FastAPI's TestClient runs endpoints in a worker thread).
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    yield factory
    engine.dispose()


@pytest.fixture
def db_session(db_session_factory):
    session = db_session_factory()
    yield session
    session.close()


@pytest.fixture
def sample_gps_points() -> list[GPSPoint]:
    t0 = datetime(2026, 8, 14, 14, 0, 0, tzinfo=IST)
    return [
        GPSPoint(t0, 12.9716, 77.5946, accuracy=5.0, speed=0.0, bearing=90.0),
        GPSPoint(t0 + timedelta(seconds=2), 12.9718, 77.5950, accuracy=5.0, speed=4.0, bearing=91.0),
        GPSPoint(t0 + timedelta(seconds=4), 12.9720, 77.5954, accuracy=6.0, speed=4.2, bearing=92.0),
        GPSPoint(t0 + timedelta(seconds=10), 12.9730, 77.5970, accuracy=5.0, speed=5.0, bearing=95.0),
    ]
