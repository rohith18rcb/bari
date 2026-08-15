"""
SQLAlchemy models for BARI.

Timestamps are stored as ISO 8601 strings (with timezone offset, e.g.
``2026-08-14T14:32:18+05:30``) rather than naive DATETIME columns, so the
original timezone (Asia/Kolkata) is never silently dropped by SQLite's
limited datetime handling. ISO 8601 strings also sort lexicographically in
the same order as chronologically, so date-range queries work directly.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class SessionRecord(Base):
    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    start_time: Mapped[str] = mapped_column(String, nullable=False)
    end_time: Mapped[str | None] = mapped_column(String, nullable=True)
    video_source: Mapped[str] = mapped_column(String, nullable=False)
    gps_source: Mapped[str] = mapped_column(String, nullable=False)
    distance_km: Mapped[float] = mapped_column(Float, default=0.0)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    total_detections: Mapped[int] = mapped_column(Integer, default=0)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(String, default=_now_iso)

    detections: Mapped[list["Detection"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class Detection(Base):
    __tablename__ = "detections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pothole_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    track_id: Mapped[int] = mapped_column(Integer, nullable=False)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.session_id"), nullable=False, index=True)

    timestamp: Mapped[str] = mapped_column(String, nullable=False, index=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    gps_accuracy: Mapped[float] = mapped_column(Float, default=0.0)
    speed: Mapped[float] = mapped_column(Float, default=0.0)
    bearing: Mapped[float] = mapped_column(Float, default=0.0)
    gps_sync_method: Mapped[str] = mapped_column(String, default="unknown")

    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    frame_count: Mapped[int] = mapped_column(Integer, default=1)
    severity: Mapped[str] = mapped_column(String, nullable=False, index=True)

    city: Mapped[str] = mapped_column(String, default="Unknown")
    state: Mapped[str] = mapped_column(String, default="Unknown")
    zone: Mapped[str] = mapped_column(String, default="Unknown", index=True)
    ward: Mapped[str] = mapped_column(String, default="Unknown", index=True)
    locality: Mapped[str] = mapped_column(String, default="Unknown", index=True)
    postcode: Mapped[str] = mapped_column(String, default="Unknown")
    formatted_address: Mapped[str] = mapped_column(String, default="Unknown")

    image_path: Mapped[str] = mapped_column(String, default="")
    annotated_image_path: Mapped[str] = mapped_column(String, default="")
    crop_image_path: Mapped[str] = mapped_column(String, default="")

    duplicate_status: Mapped[str] = mapped_column(String, default="NEW", index=True)
    duplicate_of: Mapped[str | None] = mapped_column(String, nullable=True)

    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(String, default=_now_iso)

    session: Mapped["SessionRecord"] = relationship(back_populates="detections")


class LocationCache(Base):
    __tablename__ = "location_cache"

    cache_key: Mapped[str] = mapped_column(String, primary_key=True)
    city: Mapped[str] = mapped_column(String, default="Unknown")
    state: Mapped[str] = mapped_column(String, default="Unknown")
    postcode: Mapped[str] = mapped_column(String, default="Unknown")
    locality: Mapped[str] = mapped_column(String, default="Unknown")
    formatted_address: Mapped[str] = mapped_column(String, default="Unknown")
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(String, default=_now_iso)


class SyncQueue(Base):
    """Records not yet pushed to a future central/cloud store (Phase 5 roadmap).

    Not used by V1's local dashboard, but modeled now so a future Android/cloud
    sync client can be added without a schema migration.
    """
    __tablename__ = "sync_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pothole_id: Mapped[str] = mapped_column(String, ForeignKey("detections.pothole_id"), nullable=False)
    synced: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(String, default=_now_iso)

    __table_args__ = (UniqueConstraint("pothole_id", name="uq_sync_queue_pothole"),)
