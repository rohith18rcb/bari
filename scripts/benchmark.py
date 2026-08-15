"""
benchmark.py — measures real inference/processing performance. Never
fabricates numbers: all figures come from an actual run against the given
video (or a synthetic dummy frame if no video is supplied).

Usage:
    python scripts/benchmark.py --video data/input/demo_ride.mp4
    python scripts/benchmark.py   # synthetic dummy-frame benchmark only
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import psutil

from core.config import settings
from core.device import resolve_device

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("bari.benchmark")


def benchmark_dummy(model, device: str, imgsz: int, runs: int) -> dict:
    dummy = np.random.randint(0, 255, (imgsz, imgsz, 3), dtype=np.uint8)
    for _ in range(3):
        model.predict(dummy, imgsz=imgsz, device=device, verbose=False)
    start = time.perf_counter()
    for _ in range(runs):
        model.predict(dummy, imgsz=imgsz, device=device, verbose=False)
    elapsed = time.perf_counter() - start
    ms_per_image = (elapsed / runs) * 1000
    return {"runs": runs, "ms_per_image": round(ms_per_image, 2), "fps": round(1000 / ms_per_image, 2)}


def benchmark_video(model, video_path: Path, device: str) -> dict:
    import cv2
    cap = cv2.VideoCapture(str(video_path))
    video_fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    start = time.perf_counter()
    n = 0
    for _ in model.predict(source=str(video_path), device=device, stream=True, verbose=False):
        n += 1
        if n >= 150:  # cap benchmark length for a reasonably fast run
            break
    elapsed = time.perf_counter() - start

    return {
        "video_reported_fps": round(video_fps, 2),
        "video_frame_count": frame_count,
        "frames_benchmarked": n,
        "processing_seconds": round(elapsed, 2),
        "processing_fps": round(n / elapsed, 2) if elapsed > 0 else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark BARI inference/processing performance")
    parser.add_argument("--video", type=Path, default=None)
    parser.add_argument("--weights", type=Path, default=settings.model_path)
    parser.add_argument("--imgsz", type=int, default=settings.img_size)
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--device", type=str, default=settings.device)
    args = parser.parse_args()

    weights = args.weights if args.weights.exists() else Path("yolov8n.pt")
    if not args.weights.exists():
        logger.warning("Trained weights not found at %s; benchmarking with stock yolov8n.pt instead", args.weights)

    from ultralytics import YOLO
    device = resolve_device(args.device)
    model = YOLO(str(weights))

    report = {
        "device": device,
        "cpu_count": psutil.cpu_count(logical=True),
        "cpu_percent_before": psutil.cpu_percent(interval=0.2),
        "memory_used_mb": round(psutil.Process().memory_info().rss / (1024 * 1024), 1),
        "dummy_frame_benchmark": benchmark_dummy(model, device, args.imgsz, args.runs),
    }

    if args.video and args.video.exists():
        report["video_benchmark"] = benchmark_video(model, args.video, device)
    elif args.video:
        logger.warning("Video not found: %s (skipping video benchmark)", args.video)

    report["cpu_percent_after"] = psutil.cpu_percent(interval=0.2)
    report["memory_used_mb_after"] = round(psutil.Process().memory_info().rss / (1024 * 1024), 1)

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
