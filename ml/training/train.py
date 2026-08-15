"""
train.py — trains a YOLO pothole detector on the prepared dataset.

Wraps Ultralytics YOLO training with the configuration knobs required by the
project spec (model, epochs, image size, batch size, learning rate,
confidence/IoU thresholds used later at inference, device). Automatically
uses CUDA if available, falls back to CPU otherwise, and never crashes just
because a GPU isn't present.

Usage:
    python ml/training/train.py --epochs 50 --model yolov8n.pt
    python ml/training/train.py --epochs 5 --batch 8 --device cpu   # quick smoke run
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.device import resolve_device

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("bari.train")
DEFAULT_DATA_YAML = PROJECT_ROOT / "ml" / "datasets" / "processed" / "data.yaml"
RUNS_DIR = PROJECT_ROOT / "ml" / "training" / "runs"


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the BARI pothole YOLO detector")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_YAML, help="Path to data.yaml")
    parser.add_argument("--model", type=str, default="yolov8n.pt", help="Base model / weights to start from")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--lr0", type=float, default=0.01, help="Initial learning rate")
    parser.add_argument("--conf", type=float, default=0.35, help="Confidence threshold recorded for reference (used at inference, not training)")
    parser.add_argument("--iou", type=float, default=0.45, help="IoU (NMS) threshold recorded for reference (used at inference, not training)")
    parser.add_argument("--device", type=str, default="auto", help="'auto', 'cpu', or a CUDA device index like '0'")
    parser.add_argument("--name", type=str, default="pothole_yolo")
    parser.add_argument("--patience", type=int, default=20, help="Early-stopping patience (epochs)")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    if not args.data.exists():
        raise FileNotFoundError(
            f"data.yaml not found at {args.data}. Run `python ml/datasets/prepare_dataset.py` first "
            f"(after downloading a dataset into ml/datasets/raw/)."
        )

    device = resolve_device(args.device)
    logger.info("Resolved device: %s", device)

    from ultralytics import YOLO

    logger.info("Loading base model: %s", args.model)
    model = YOLO(args.model)

    logger.info(
        "Starting training: data=%s epochs=%d imgsz=%d batch=%d lr0=%s device=%s",
        args.data, args.epochs, args.imgsz, args.batch, args.lr0, device,
    )
    results = model.train(
        data=str(args.data),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        lr0=args.lr0,
        device=device,
        project=str(RUNS_DIR),
        name=args.name,
        patience=args.patience,
        workers=args.workers,
        exist_ok=True,
        plots=True,
    )

    save_dir = Path(results.save_dir)
    best = save_dir / "weights" / "best.pt"
    last = save_dir / "weights" / "last.pt"
    logger.info("Training complete.")
    logger.info("Best weights: %s (exists=%s)", best, best.exists())
    logger.info("Last weights: %s (exists=%s)", last, last.exists())
    logger.info("Results / plots / metrics saved under: %s", save_dir)


if __name__ == "__main__":
    main()
