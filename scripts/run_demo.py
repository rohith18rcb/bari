"""
run_demo.py — orchestrates the full BARI demo end to end:

  1. Generate a simulated Bengaluru GPS route
  2. Build a synthetic demo ride video from real (licensed) dataset photos
  3. Run the real detection+tracking+GPS-sync+GIS+DB pipeline (main.py) on them
  4. Populate the database with additional simulated sessions for a richer dashboard
  5. Print next steps (launch dashboard, exports)

Usage:
    python scripts/run_demo.py
"""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.config import settings

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("bari.run_demo")


def run(cmd: list[str]) -> int:
    logger.info("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    return result.returncode


def main() -> int:
    python = sys.executable
    gps_path = PROJECT_ROOT / "data" / "input" / "demo_ride.csv"
    video_path = PROJECT_ROOT / "data" / "input" / "demo_ride.mp4"

    rc = run([python, "scripts/generate_demo_gps.py", "--duration", "150", "--out", str(gps_path)])
    if rc != 0:
        return rc

    if not video_path.exists():
        rc = run([python, "scripts/generate_demo_video.py", "--duration", "150", "--out", str(video_path)])
        if rc != 0:
            return rc
    else:
        logger.info("Demo video already exists at %s (skipping regeneration)", video_path)

    weights = settings.model_path
    if not weights.exists():
        logger.warning(
            "No trained model found at %s. Falling back to a stock COCO yolov8n.pt for the pipeline demo "
            "(it will NOT detect potholes correctly — train first with `python ml/training/train.py` for a "
            "real demo). Proceeding anyway so the rest of the pipeline (GPS sync, GIS, DB, dashboard) can "
            "still be exercised.", weights,
        )
        weights_arg = ["--weights", "yolov8n.pt"]
    else:
        weights_arg = []

    rc = run([python, "main.py", "--video", str(video_path), "--gps", str(gps_path), "--demo", *weights_arg])
    if rc != 0:
        return rc

    rc = run([python, "scripts/generate_demo_data.py", "--sessions", "8", "--no-geocode"])
    if rc != 0:
        return rc

    logger.info("=" * 60)
    logger.info("DEMO COMPLETE")
    logger.info("Launch the dashboard:  python dashboard/app.py")
    logger.info("Then open:             http://%s:%d", settings.dashboard_host, settings.dashboard_port)
    logger.info("Export data:           python export_data.py --format csv")
    logger.info("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
