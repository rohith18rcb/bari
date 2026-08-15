"""
clear_demo_data.py — removes all is_demo=True records (and their evidence
images) from the database, leaving only real captured data (from main.py
video runs or the mobile/web ingest pipeline).

Usage:
    python scripts/clear_demo_data.py
    python scripts/clear_demo_data.py --yes   # skip confirmation prompt
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select

from db.database import SessionLocal, init_db
from db.models import Detection, SessionRecord

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("bari.clear_demo_data")


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove all demo (is_demo=True) sessions and detections")
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    args = parser.parse_args()

    init_db()
    with SessionLocal() as db:
        demo_detections = list(db.execute(select(Detection).where(Detection.is_demo.is_(True))).scalars())
        demo_sessions = list(db.execute(select(SessionRecord).where(SessionRecord.is_demo.is_(True))).scalars())

    print(f"Found {len(demo_detections)} demo detection(s) and {len(demo_sessions)} demo session(s).")
    if not demo_detections and not demo_sessions:
        print("Nothing to remove.")
        return 0

    if not args.yes:
        confirm = input("Remove all demo data permanently? [y/N] ").strip().lower()
        if confirm != "y":
            print("Cancelled.")
            return 1

    removed_files = 0
    for d in demo_detections:
        for path_str in (d.image_path, d.annotated_image_path, d.crop_image_path):
            if path_str:
                p = Path(path_str)
                if p.exists():
                    p.unlink()
                    removed_files += 1

    with SessionLocal() as db:
        for d in demo_detections:
            row = db.get(Detection, d.id)
            if row is not None:
                db.delete(row)
        for s in demo_sessions:
            row = db.get(SessionRecord, s.session_id)
            if row is not None:
                db.delete(row)
        db.commit()

    logger.info("Removed %d demo detection(s), %d demo session(s), %d evidence file(s).",
                len(demo_detections), len(demo_sessions), removed_files)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
