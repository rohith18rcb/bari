# Model Deployment

## Dataset

See `ml/datasets/processed/dataset_info.json` (written by
`ml/datasets/prepare_dataset.py`) for the exact recorded provenance:

- **Name:** Potholes Detection Dataset (Roboflow Universe,
  `project-ssayl/potholes-detection-d4rma` v1)
- **Source:** downloaded from its Hugging Face mirror,
  https://huggingface.co/datasets/Ryukijano/Pothole-detection-Yolov8
  (unmodified re-export of https://universe.roboflow.com/project-ssayl/potholes-detection-d4rma/dataset/1)
- **License:** CC BY 4.0
- **Classes:** 1 (`pothole`)
- **Images:** 300 total — 100 train / 100 valid / 100 test, YOLO-txt format

This is a small dataset by production standards. It was chosen because it is
real, licensed, pre-annotated, and fits this project's disk/time budget — see
"Limitations" below and in the main README for how to swap in a larger
dataset without touching any code (`ml/datasets/prepare_dataset.py` only
depends on the raw folder layout, not this specific source).

## Training

```bash
python ml/training/train.py --epochs 60 --imgsz 640 --batch 16 --device auto
```

- Base model: `yolov8n.pt` (Ultralytics YOLOv8 nano, transfer-learned)
- Device: CUDA if `torch.cuda.is_available()`, else CPU automatically
  (`core/device.py`) — this build ran on **CPU** (see note below)
- Outputs: `ml/training/runs/pothole_yolo/weights/{best,last}.pt`, training
  curves, PR curve, confusion matrix, sample-prediction mosaics — all
  written automatically by Ultralytics under the run directory

**Hardware note:** this machine has an NVIDIA GPU, but at build time the
project's working disk had only ~7GB free. A CUDA-enabled PyTorch build
alone is 2-3GB; CPU-only PyTorch is ~150MB. To fit the full stack (torch +
ultralytics + opencv + onnxruntime) and the dataset in the available space,
this build installs **CPU-only PyTorch**. `core/device.py` still
auto-detects CUDA — on a machine with more disk headroom, installing the
CUDA build of PyTorch (`pip install torch --index-url
https://download.pytorch.org/whl/cu121` or similar) is a drop-in swap; no
application code changes.

## Evaluation

```bash
python ml/evaluation/evaluate.py --split test
```

Runs Ultralytics' validation loop on the held-out **test** split (never
used for training or checkpoint selection) and writes
`ml/evaluation/reports/evaluation_report.json`. Metrics explained:

- **Precision** — of predicted potholes, the fraction that were correct.
  Low precision = many false alarms.
- **Recall** — of actual potholes, the fraction the model found. Low
  recall = many misses.
- **mAP@50** — mean Average Precision at IoU ≥ 0.50 (lenient overlap
  threshold); the standard "did it roughly find it" metric.
- **mAP@50-95** — mAP averaged over IoU thresholds 0.50-0.95 (stricter,
  rewards precisely-located boxes).
- **F1** — harmonic mean of precision and recall.
- **Inference speed** — ms/image (preprocess + inference + NMS) on the
  device evaluation ran on.

**Actual metrics from this build are recorded in
`ml/evaluation/reports/evaluation_report.json`** and summarized in the main
README / final report — never fabricated. If that file's `status` is
`NOT_EXECUTED`, training did not complete in this environment and no
metrics should be assumed.

## ONNX export

```bash
python ml/export/export_onnx.py
```

Exports `best.pt` to ONNX (`opset` default from Ultralytics, `simplify=True`)
and benchmarks CPU inference latency for both the PyTorch and ONNX Runtime
paths, writing `ml/export/export_report.json`. ONNX is the artifact a future
mobile client would consume via ONNX Runtime Mobile — see
`docs/android_deployment.md`.

## Limitations of this V1 model

- Trained on only 100 training images — expect it to generalize narrowly
  (road types/lighting close to the source dataset) rather than robustly
  across all real-world Bengaluru conditions.
- Single class (`pothole`) — no severity, no other road-defect types.
- CPU training with a `yolov8n` (nano) backbone trades accuracy for speed;
  a larger backbone (`yolov8s`/`yolov8m`) trained longer, with more data
  and GPU, would materially improve mAP.
- No hyperparameter search was run — `train.py` exposes the knobs
  (`--lr0`, `--batch`, `--imgsz`, etc.) for a future sweep.

Swapping in more data or a larger backbone requires no architecture
changes — just a bigger `ml/datasets/raw/` folder and different
`--model`/`--epochs` flags to `train.py`.
