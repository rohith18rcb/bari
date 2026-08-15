"""
prepare_dataset.py — normalizes a raw downloaded YOLO-format dataset into
ml/datasets/processed/, with a clean data.yaml (proper class names, relative
paths) and a dataset_info.json recording provenance (name/source/license/
image counts/classes) per the project's "no invented dataset claims" rule.

Usage:
    python ml/datasets/prepare_dataset.py
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

import yaml

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("bari.prepare_dataset")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RAW_DIR = PROJECT_ROOT / "ml" / "datasets" / "raw" / "pothole_hf"
PROCESSED_DIR = PROJECT_ROOT / "ml" / "datasets" / "processed"

CLASS_NAMES = ["pothole"]

DATASET_INFO = {
    "dataset_name": "Potholes Detection Dataset (Roboflow Universe, project-ssayl/potholes-detection-d4rma v1)",
    "source": "https://universe.roboflow.com/project-ssayl/potholes-detection-d4rma/dataset/1 "
              "(mirrored, unmodified, at https://huggingface.co/datasets/Ryukijano/Pothole-detection-Yolov8)",
    "license": "CC BY 4.0",
    "classes": CLASS_NAMES,
    "note": "Single-class pothole object detection dataset in YOLO txt format, exported by Roboflow.",
}


def _copy_split(split: str) -> tuple[int, int]:
    src_images = RAW_DIR / split / "images"
    src_labels = RAW_DIR / split / "labels"
    dst_images = PROCESSED_DIR / split / "images"
    dst_labels = PROCESSED_DIR / split / "labels"
    dst_images.mkdir(parents=True, exist_ok=True)
    dst_labels.mkdir(parents=True, exist_ok=True)

    n_img = 0
    if src_images.exists():
        for f in src_images.iterdir():
            if f.is_file():
                shutil.copy2(f, dst_images / f.name)
                n_img += 1

    n_lbl = 0
    if src_labels.exists():
        for f in src_labels.iterdir():
            if f.is_file():
                shutil.copy2(f, dst_labels / f.name)
                n_lbl += 1

    return n_img, n_lbl


def prepare() -> Path:
    if not RAW_DIR.exists():
        raise FileNotFoundError(
            f"Raw dataset not found at {RAW_DIR}. Run the dataset download step first, or place a "
            f"YOLO-format dataset (train/valid/test with images/ and labels/ subfolders) there manually."
        )

    counts = {}
    for split in ("train", "valid", "test"):
        n_img, n_lbl = _copy_split(split)
        counts[split] = {"images": n_img, "labels": n_lbl}
        logger.info("Split '%s': %d images, %d labels", split, n_img, n_lbl)

    data_yaml = {
        "path": str(PROCESSED_DIR),
        "train": "train/images",
        "val": "valid/images",
        "test": "test/images",
        "nc": len(CLASS_NAMES),
        "names": CLASS_NAMES,
    }
    data_yaml_path = PROCESSED_DIR / "data.yaml"
    with open(data_yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data_yaml, f, sort_keys=False)
    logger.info("Wrote %s", data_yaml_path)

    info = dict(DATASET_INFO)
    info["counts"] = counts
    info["total_images"] = sum(c["images"] for c in counts.values())
    with open(PROCESSED_DIR / "dataset_info.json", "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2)
    logger.info("Wrote dataset_info.json (total_images=%d)", info["total_images"])

    return data_yaml_path


if __name__ == "__main__":
    path = prepare()
    print(f"Dataset prepared. data.yaml at: {path}")
