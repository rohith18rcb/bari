"""
detect.py — single image/directory pothole detection smoke test (no GPS,
no tracking, no database). For full video+GPS pipeline use main.py.

Usage:
    python ml/inference/detect.py --source path/to/image.jpg
    python ml/inference/detect.py --source path/to/folder/
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.config import settings
from core.device import resolve_device

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("bari.detect")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run pothole detection on an image or folder")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--weights", type=Path, default=settings.model_path)
    parser.add_argument("--conf", type=float, default=settings.confidence_threshold)
    parser.add_argument("--iou", type=float, default=settings.iou_threshold)
    parser.add_argument("--device", type=str, default=settings.device)
    parser.add_argument("--out", type=Path, default=settings.output_path / "detect")
    args = parser.parse_args()

    if not args.weights.exists():
        logger.error("Weights not found at %s. Train a model first (ml/training/train.py) or point --weights at yolov8n.pt for a COCO smoke test.", args.weights)
        return 1
    if not args.source.exists():
        logger.error("Source not found: %s", args.source)
        return 1

    from ultralytics import YOLO

    device = resolve_device(args.device)
    model = YOLO(str(args.weights))
    logger.info("Running inference: source=%s conf=%s iou=%s device=%s", args.source, args.conf, args.iou, device)

    results = model.predict(
        source=str(args.source), conf=args.conf, iou=args.iou, device=device,
        save=True, project=str(args.out.parent), name=args.out.name, exist_ok=True,
    )

    for r in results:
        logger.info("%s -> %d detection(s)", Path(r.path).name, len(r.boxes) if r.boxes is not None else 0)

    logger.info("Annotated output saved under: %s", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
