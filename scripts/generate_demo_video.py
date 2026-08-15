"""
generate_demo_video.py — builds a synthetic demo "ride" video for pipeline
demonstration when real Bengaluru road footage isn't available.

IMPORTANT — provenance: this composites real, licensed pothole photographs
from the training dataset's held-out TEST split (never seen during training,
so detections on it reflect genuine model performance, not memorization)
into a video by holding each photo for a couple of seconds with a synthetic
"Ken Burns" pan/zoom to emulate camera motion. This is a DEMO video for
exercising the CV+GPS+GIS pipeline end-to-end — it is explicitly NOT real
collected Bengaluru road footage, and must never be presented as such.

Usage:
    python scripts/generate_demo_video.py --duration 120 --out data/input/demo_ride.mp4
"""
from __future__ import annotations

import argparse
import logging
import random
from pathlib import Path

import cv2
import numpy as np

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("bari.generate_demo_video")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_IMAGE_SOURCE = PROJECT_ROOT / "ml" / "datasets" / "processed" / "test" / "images"
OUT_WIDTH, OUT_HEIGHT = 960, 540


def ken_burns_frames(image: np.ndarray, num_frames: int, rng: random.Random) -> list[np.ndarray]:
    """Generate a short pan/zoom sequence from a single still image."""
    h, w = image.shape[:2]
    zoom_start = rng.uniform(1.0, 1.08)
    zoom_end = rng.uniform(1.12, 1.25)
    dx = rng.uniform(-0.04, 0.04)
    dy = rng.uniform(-0.03, 0.03)

    frames = []
    for i in range(num_frames):
        t = i / max(num_frames - 1, 1)
        zoom = zoom_start + (zoom_end - zoom_start) * t
        crop_w, crop_h = w / zoom, h / zoom
        cx = w / 2 + dx * w * t
        cy = h / 2 + dy * h * t
        x1 = int(max(0, min(w - crop_w, cx - crop_w / 2)))
        y1 = int(max(0, min(h - crop_h, cy - crop_h / 2)))
        crop = image[y1:y1 + int(crop_h), x1:x1 + int(crop_w)]
        resized = cv2.resize(crop, (OUT_WIDTH, OUT_HEIGHT), interpolation=cv2.INTER_LINEAR)
        frames.append(resized)
    return frames


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a synthetic demo ride video from real dataset test images")
    parser.add_argument("--images-dir", type=Path, default=DEFAULT_IMAGE_SOURCE)
    parser.add_argument("--out", type=Path, default=Path("data/input/demo_ride.mp4"))
    parser.add_argument("--duration", type=int, default=120, help="Target total video duration (seconds)")
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument("--seconds-per-clip", type=float, default=3.0, help="How long each still image is shown for")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if not args.images_dir.exists():
        logger.error("Image source directory not found: %s. Run ml/datasets/prepare_dataset.py first.", args.images_dir)
        return 1

    images = sorted(p for p in args.images_dir.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    if not images:
        logger.error("No images found in %s", args.images_dir)
        return 1

    rng = random.Random(args.seed)
    rng.shuffle(images)

    n_clips = max(int(args.duration / args.seconds_per_clip), 1)
    n_clips = min(n_clips, len(images))
    selected = images[:n_clips]
    frames_per_clip = int(args.fps * args.seconds_per_clip)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(args.out), cv2.VideoWriter_fourcc(*"mp4v"), args.fps, (OUT_WIDTH, OUT_HEIGHT))

    total_frames = 0
    for i, img_path in enumerate(selected):
        img = cv2.imread(str(img_path))
        if img is None:
            logger.warning("Could not read %s, skipping", img_path)
            continue
        for frame in ken_burns_frames(img, frames_per_clip, rng):
            writer.write(frame)
            total_frames += 1
        if (i + 1) % 10 == 0:
            logger.info("Composited %d/%d clips", i + 1, len(selected))

    writer.release()
    duration_actual = total_frames / args.fps
    logger.info(
        "[DEMO VIDEO — synthetic composite, not real footage] Wrote %s (%d frames, %.1fs, %d source images from held-out test split)",
        args.out, total_frames, duration_actual, len(selected),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
