"""
validate_dataset.py — sanity-checks a YOLO-format object detection dataset
before training: missing images/labels, malformed label lines, invalid
bounding boxes, out-of-range class IDs, and duplicate files (by content hash).

Usage:
    python ml/datasets/validate_dataset.py --data ml/datasets/processed/data.yaml
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("bari.validate_dataset")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}


@dataclass
class ValidationReport:
    split: str
    num_images: int = 0
    num_labels: int = 0
    missing_labels: list[str] = field(default_factory=list)
    missing_images: list[str] = field(default_factory=list)
    malformed_labels: list[str] = field(default_factory=list)
    invalid_boxes: list[str] = field(default_factory=list)
    invalid_class_ids: list[str] = field(default_factory=list)
    duplicate_images: list[str] = field(default_factory=list)
    empty_labels: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not (
            self.missing_labels or self.missing_images or self.malformed_labels
            or self.invalid_boxes or self.invalid_class_ids
        )

    def summary(self) -> str:
        lines = [
            f"--- Split: {self.split} ---",
            f"Images: {self.num_images}, Labels: {self.num_labels}",
            f"Missing labels: {len(self.missing_labels)}",
            f"Missing images (label with no image): {len(self.missing_images)}",
            f"Malformed label lines: {len(self.malformed_labels)}",
            f"Invalid bounding boxes: {len(self.invalid_boxes)}",
            f"Invalid class IDs: {len(self.invalid_class_ids)}",
            f"Duplicate images (by content hash): {len(self.duplicate_images)}",
            f"Empty label files (no objects): {len(self.empty_labels)}",
            f"VALID: {self.is_valid}",
        ]
        return "\n".join(lines)


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_split(images_dir: Path, labels_dir: Path, num_classes: int, split_name: str) -> ValidationReport:
    report = ValidationReport(split=split_name)

    if not images_dir.exists():
        logger.warning("Images dir missing entirely: %s", images_dir)
        return report
    if not labels_dir.exists():
        logger.warning("Labels dir missing entirely: %s", labels_dir)

    image_files = sorted(p for p in images_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    label_files = sorted(labels_dir.glob("*.txt")) if labels_dir.exists() else []
    label_stems = {p.stem for p in label_files}
    image_stems = {p.stem for p in image_files}

    report.num_images = len(image_files)
    report.num_labels = len(label_files)

    for img in image_files:
        if img.stem not in label_stems:
            report.missing_labels.append(str(img))

    for lbl in label_files:
        if lbl.stem not in image_stems:
            report.missing_images.append(str(lbl))

    seen_hashes: dict[str, str] = {}
    for img in image_files:
        h = _file_hash(img)
        if h in seen_hashes:
            report.duplicate_images.append(f"{img} duplicates {seen_hashes[h]}")
        else:
            seen_hashes[h] = str(img)

    for lbl in label_files:
        text = lbl.read_text(encoding="utf-8").strip()
        if not text:
            report.empty_labels.append(str(lbl))
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            parts = line.split()
            if len(parts) != 5:
                report.malformed_labels.append(f"{lbl}:{line_no} -> '{line}'")
                continue
            try:
                cls_id = int(float(parts[0]))
                x, y, w, h_ = (float(p) for p in parts[1:])
            except ValueError:
                report.malformed_labels.append(f"{lbl}:{line_no} -> '{line}' (non-numeric)")
                continue

            if cls_id < 0 or cls_id >= num_classes:
                report.invalid_class_ids.append(f"{lbl}:{line_no} class_id={cls_id}")

            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 and 0.0 < w <= 1.0 and 0.0 < h_ <= 1.0):
                report.invalid_boxes.append(f"{lbl}:{line_no} box=({x},{y},{w},{h_})")

    return report


def validate_dataset(data_yaml: Path) -> list[ValidationReport]:
    with open(data_yaml, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    num_classes = int(config["nc"])
    root = data_yaml.parent
    reports = []

    for split in ("train", "val", "test"):
        if split not in config:
            continue
        images_rel = config[split]
        images_dir = (root / images_rel).resolve()
        labels_dir = Path(str(images_dir).replace("images", "labels"))
        reports.append(validate_split(images_dir, labels_dir, num_classes, split))

    return reports


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a YOLO-format dataset")
    parser.add_argument("--data", type=Path, default=Path("ml/datasets/processed/data.yaml"))
    args = parser.parse_args()

    if not args.data.exists():
        logger.error("data.yaml not found: %s", args.data)
        return 1

    reports = validate_dataset(args.data)
    all_valid = True
    for report in reports:
        print(report.summary())
        print()
        all_valid = all_valid and report.is_valid

    if all_valid:
        logger.info("Dataset validation PASSED.")
        return 0
    else:
        logger.error("Dataset validation FOUND ISSUES (see above).")
        return 1


if __name__ == "__main__":
    sys.exit(main())
