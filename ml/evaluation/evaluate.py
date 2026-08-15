"""
evaluate.py — runs real evaluation of a trained YOLO pothole model and
produces a clear metrics report. Never fabricates numbers: if no trained
model / dataset is available, it reports NOT EXECUTED with a reason instead
of inventing metrics.

Metrics (from Ultralytics' validation on the held-out split):
  Precision   — of predicted potholes, fraction that were correct (low
                precision = many false alarms)
  Recall      — of actual potholes, fraction the model found (low recall
                = many misses)
  mAP@50      — mean Average Precision at IoU >= 0.50 (a lenient overlap
                threshold; the standard "did it roughly find it" metric)
  mAP@50-95   — mAP averaged over IoU thresholds 0.50-0.95 (stricter,
                rewards precisely-located boxes; harder to score well on)
  F1          — harmonic mean of precision and recall
  Inference speed — milliseconds per image (preprocess + inference + NMS)

Usage:
    python ml/evaluation/evaluate.py --weights ml/training/runs/pothole_yolo/weights/best.pt
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.device import resolve_device

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("bari.evaluate")

DEFAULT_DATA_YAML = PROJECT_ROOT / "ml" / "datasets" / "processed" / "data.yaml"
DEFAULT_WEIGHTS = PROJECT_ROOT / "ml" / "training" / "runs" / "pothole_yolo" / "weights" / "best.pt"
REPORT_DIR = PROJECT_ROOT / "ml" / "evaluation" / "reports"


def evaluate(weights: Path, data_yaml: Path, split: str, device: str, imgsz: int) -> dict:
    from ultralytics import YOLO

    model = YOLO(str(weights))
    metrics = model.val(data=str(data_yaml), split=split, device=device, imgsz=imgsz, plots=True)

    precision = float(metrics.box.mp)
    recall = float(metrics.box.mr)
    map50 = float(metrics.box.map50)
    map50_95 = float(metrics.box.map)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    speed = metrics.speed  # dict: preprocess, inference, postprocess (ms/image)
    total_ms = sum(speed.values())

    report = {
        "status": "EXECUTED",
        "weights": str(weights),
        "dataset": str(data_yaml),
        "split": split,
        "device": device,
        "num_images": int(metrics.seen) if hasattr(metrics, "seen") else None,
        "metrics": {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "map50": round(map50, 4),
            "map50_95": round(map50_95, 4),
            "f1": round(f1, 4),
        },
        "inference_speed_ms": {
            "preprocess": round(speed.get("preprocess", 0.0), 3),
            "inference": round(speed.get("inference", 0.0), 3),
            "postprocess": round(speed.get("postprocess", 0.0), 3),
            "total": round(total_ms, 3),
        },
        "fps_estimate": round(1000.0 / total_ms, 2) if total_ms > 0 else None,
        "plots_dir": str(metrics.save_dir),
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the BARI pothole YOLO model")
    parser.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_YAML)
    parser.add_argument("--split", type=str, default="test", choices=["train", "val", "test"])
    parser.add_argument("--device", type=str, default="auto")
    parser.add_argument("--imgsz", type=int, default=640)
    args = parser.parse_args()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / "evaluation_report.json"

    if not args.weights.exists():
        report = {
            "status": "NOT_EXECUTED",
            "reason": f"No trained weights found at {args.weights}. Run ml/training/train.py first.",
        }
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        logger.warning("MODEL EVALUATION: NOT EXECUTED — %s", report["reason"])
        print(json.dumps(report, indent=2))
        return 1

    if not args.data.exists():
        report = {
            "status": "NOT_EXECUTED",
            "reason": f"Dataset not found at {args.data}. Run ml/datasets/prepare_dataset.py first.",
        }
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        logger.warning("MODEL EVALUATION: NOT EXECUTED — %s", report["reason"])
        print(json.dumps(report, indent=2))
        return 1

    device = resolve_device(args.device)
    report = evaluate(args.weights, args.data, args.split, device, args.imgsz)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    m = report["metrics"]
    print("=" * 50)
    print("MODEL EVALUATION")
    print("=" * 50)
    print(f"Split:          {args.split}")
    print(f"Precision:      {m['precision']}")
    print(f"Recall:         {m['recall']}")
    print(f"mAP50:          {m['map50']}")
    print(f"mAP50-95:       {m['map50_95']}")
    print(f"F1:             {m['f1']}")
    print(f"Inference:      {report['inference_speed_ms']['total']} ms/image "
          f"(~{report['fps_estimate']} FPS on {device})")
    print(f"Plots saved to: {report['plots_dir']}")
    print(f"Report saved to: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
