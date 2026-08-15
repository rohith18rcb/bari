"""
export_onnx.py — exports a trained YOLO pothole model to ONNX and benchmarks
PyTorch vs ONNX Runtime inference speed + reports model file sizes. This is
the artifact a future Android/mobile client (ONNX Runtime Mobile / NNAPI)
would consume — see docs/android_deployment.md.

Usage:
    python ml/export/export_onnx.py --weights ml/training/runs/pothole_yolo/weights/best.pt
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("bari.export_onnx")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_WEIGHTS = PROJECT_ROOT / "ml" / "training" / "runs" / "pothole_yolo" / "weights" / "best.pt"
REPORT_PATH = PROJECT_ROOT / "ml" / "export" / "export_report.json"


def benchmark_pytorch(weights: Path, imgsz: int, runs: int) -> float:
    from ultralytics import YOLO
    model = YOLO(str(weights))
    dummy = np.random.randint(0, 255, (imgsz, imgsz, 3), dtype=np.uint8)

    for _ in range(3):  # warmup
        model.predict(dummy, imgsz=imgsz, verbose=False, device="cpu")

    start = time.perf_counter()
    for _ in range(runs):
        model.predict(dummy, imgsz=imgsz, verbose=False, device="cpu")
    elapsed = time.perf_counter() - start
    return (elapsed / runs) * 1000.0  # ms/image


def benchmark_onnx(onnx_path: Path, imgsz: int, runs: int) -> float:
    import onnxruntime as ort

    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    dummy = np.random.rand(1, 3, imgsz, imgsz).astype(np.float32)

    for _ in range(3):
        session.run(None, {input_name: dummy})

    start = time.perf_counter()
    for _ in range(runs):
        session.run(None, {input_name: dummy})
    elapsed = time.perf_counter() - start
    return (elapsed / runs) * 1000.0


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the BARI pothole model to ONNX and benchmark it")
    parser.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--runs", type=int, default=20, help="Benchmark iterations")
    parser.add_argument("--skip-benchmark", action="store_true")
    args = parser.parse_args()

    if not args.weights.exists():
        report = {"status": "NOT_EXECUTED", "reason": f"No trained weights found at {args.weights}. Run ml/training/train.py first."}
        REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
        logger.warning("ONNX EXPORT: NOT EXECUTED — %s", report["reason"])
        print(json.dumps(report, indent=2))
        return 1

    from ultralytics import YOLO

    model = YOLO(str(args.weights))
    logger.info("Exporting to ONNX (imgsz=%d)...", args.imgsz)
    onnx_path = Path(model.export(format="onnx", imgsz=args.imgsz, simplify=True, dynamic=False))
    logger.info("Exported: %s", onnx_path)

    pt_size_mb = args.weights.stat().st_size / (1024 * 1024)
    onnx_size_mb = onnx_path.stat().st_size / (1024 * 1024)

    report = {
        "status": "EXECUTED",
        "weights": str(args.weights),
        "onnx_path": str(onnx_path),
        "imgsz": args.imgsz,
        "model_size_mb": {
            "pytorch": round(pt_size_mb, 2),
            "onnx": round(onnx_size_mb, 2),
        },
    }

    if not args.skip_benchmark:
        logger.info("Benchmarking PyTorch inference (%d runs, CPU)...", args.runs)
        pt_ms = benchmark_pytorch(args.weights, args.imgsz, args.runs)
        logger.info("Benchmarking ONNX Runtime inference (%d runs, CPU)...", args.runs)
        onnx_ms = benchmark_onnx(onnx_path, args.imgsz, args.runs)
        report["benchmark_ms_per_image_cpu"] = {
            "pytorch": round(pt_ms, 2),
            "onnxruntime": round(onnx_ms, 2),
        }
        report["speedup_onnx_vs_pytorch"] = round(pt_ms / onnx_ms, 2) if onnx_ms > 0 else None

    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    logger.info("Export report saved to %s", REPORT_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
