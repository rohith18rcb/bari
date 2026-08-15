"""ID generators for sessions and pothole events."""
from __future__ import annotations

import secrets
from datetime import datetime


def generate_session_id(start_time: datetime) -> str:
    """SES-YYYYMMDD-HHMMSS-XXXX (XXXX = random hex to avoid collisions)."""
    stamp = start_time.strftime("%Y%m%d-%H%M%S")
    suffix = secrets.token_hex(2).upper()
    return f"SES-{stamp}-{suffix}"


def format_pothole_id(sequence: int) -> str:
    """PTH-000001, PTH-000002, ... (sequence is a monotonic DB counter)."""
    return f"PTH-{sequence:06d}"
