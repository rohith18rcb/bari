# BARI — Bengaluru AI Road Intelligence

AI pothole detection, GPS mapping, Bengaluru GIS, and analytics — built as a
demonstrable computer vision / ML engineering portfolio project.

> **Honest scope note:** this is a laptop/video-based V1 pipeline. It does
> not detect every pothole in Bengaluru, GPS accuracy is only as good as the
> input device, severity is an estimated heuristic (not a certified
> road-engineering measurement), and there is no on-device Android app yet
> (see [Future Roadmap](#future-roadmap)). What *is* real: the trained CV
> model, the GPS synchronization math, the GIS ward resolution against real
> BBMP boundaries, the SQLite database, and the dashboard — all runnable
> end-to-end on real input.

## 1. Project overview

```
VIDEO + GPS CSV -> YOLO -> ByteTrack -> Pothole Event Engine -> GPS sync
  -> Bengaluru Location (ward + reverse geocode) -> Severity -> Duplicate check
  -> SQLite -> Annotated Video + Interactive Map + Analytics + CSV/JSON export
```

## 2. Why this project exists

Municipal pothole reporting is manual and unsystematic. BARI demonstrates
how a simple video + GPS capture (the same data a phone produces) can be
turned into structured, geolocated, queryable road-condition data using a
real trained computer vision model — end to end, not just a notebook demo.

## 3. Architecture

Full diagrams and component breakdown: [`docs/architecture.md`](docs/architecture.md).

## 4. Features

- Custom-trained YOLOv8 pothole detector (real, licensed dataset — not stock COCO)
- ByteTrack multi-object tracking with persistence-based event confirmation
- Two-level duplicate detection (same-pass tracking + cross-session GPS proximity)
- Real GPS timestamp synchronization (nearest / interpolated, gap- and offset-aware)
- Real Bengaluru ward boundaries (BBMP GeoJSON, point-in-polygon)
- Cached, rate-limited Nominatim reverse geocoding
- Transparent, tunable severity heuristic
- SQLite + SQLAlchemy database (sessions, detections, geocode cache)
- FastAPI + Leaflet + Chart.js dashboard: map, filters, analytics, evidence viewer
- CSV / JSON export (CLI + dashboard download buttons)
- ONNX export + PyTorch-vs-ONNXRuntime benchmarking
- Full demo mode (simulated GPS route + synthetic composite video from real dataset photos)
- Automated test suite (62 tests) covering GPS sync, geo math, severity, DB, GIS, export, API, validation

## 5. ML pipeline

`Video frame -> YOLOv8 inference -> ByteTrack -> per-track accumulation
-> confirm after MIN_TRACK_FRAMES -> representative box`. See
[`docs/model_deployment.md`](docs/model_deployment.md) for training/eval/export detail.

## 6. Dataset

**Potholes Detection Dataset** (Roboflow Universe,
`project-ssayl/potholes-detection-d4rma` v1), mirrored on Hugging Face
(`Ryukijano/Pothole-detection-Yolov8`), **CC BY 4.0**, 300 images
(100 train / 100 valid / 100 test), 1 class (`pothole`). Downloaded and
prepared automatically by `ml/datasets/prepare_dataset.py`; full recorded
provenance in `ml/datasets/processed/dataset_info.json`. Validated (missing
files, malformed labels, invalid boxes, class IDs, duplicates) by
`ml/datasets/validate_dataset.py` — **0 issues found** on this dataset.

To use a different/larger dataset, drop it (YOLO format: `train/valid/test`
each with `images/` + `labels/`) into `ml/datasets/raw/pothole_hf/` and
rerun `prepare_dataset.py` — no code changes needed.

## 7. Training

```bash
python ml/training/train.py --epochs 60 --imgsz 640 --batch 16 --device auto
```

Auto-detects CUDA, falls back to CPU (see hardware note in
[`docs/model_deployment.md`](docs/model_deployment.md)). Saves best/last
weights, training curves, PR curve, confusion matrix under
`ml/training/runs/pothole_yolo/`.

## 8. Evaluation

```bash
python ml/evaluation/evaluate.py --split test
```

**Actual metrics from this build** (held-out test split — see
`ml/evaluation/reports/evaluation_report.json`):

```
[EVALUATION_METRICS_PLACEHOLDER]
```

Metric definitions are in [`docs/model_deployment.md`](docs/model_deployment.md#evaluation).

## 9. Video inference

```bash
python main.py --video data/input/ride01.mp4 --gps data/input/ride01.csv
```

Runs the full pipeline: detection, tracking, event confirmation, GPS sync,
location resolution, severity, duplicate check, evidence saving, DB writes,
and produces an annotated output video at `data/output/<session_id>_annotated.mp4`.

## 10. GPS synchronization

See [`docs/architecture.md`](docs/architecture.md#gps-synchronization-detail)
and `core/gps_sync.py`. Never assumes "frame 0 = GPS row 0" — does
nearest/interpolated lookup, flags stale/low-accuracy fixes, supports a
configurable clock offset.

## 11. GIS

Real BBMP ward boundaries (243 wards, CC BY-SA 2.5 IN, see
`data/bengaluru/README.md`) via point-in-polygon (`core/boundaries.py`).
Zone boundaries are **not bundled** (no clearly-licensed public dataset was
found) — zone resolves to `"Unknown"` rather than fabricated data; see
`data/bengaluru/README.md` for how to add one.

## 12. Database

SQLite via SQLAlchemy (`db/models.py`, `db/crud.py`): `sessions`,
`detections`, `location_cache` (persistent reverse-geocode cache),
`sync_queue` (reserved for future cloud sync, unused in V1).

## 13. Dashboard

```bash
python dashboard/app.py
# open http://127.0.0.1:8000
```

FastAPI JSON API (`dashboard/app.py`) + a Leaflet/Chart.js single-page
frontend (`dashboard/static/`): live stats, filterable map (severity/zone/
ward/locality/date/confidence/session), analytics charts, a detection
table with an evidence-image detail view, and CSV/JSON export buttons.
Demo-generated records are visibly tagged `DEMO` throughout.

## 14. Demo mode

```bash
python scripts/run_demo.py
```

Generates a simulated Bengaluru GPS route (Majestic → Shivajinagar →
Indiranagar → KR Puram → Whitefield — clearly labeled simulated waypoints,
`scripts/generate_demo_gps.py`), a synthetic demo video composited from
real held-out test-split dataset photos with a Ken Burns pan/zoom
(`scripts/generate_demo_video.py` — **not real Bengaluru footage**, labeled
as such in logs and DB), runs it through the real pipeline (`main.py
--demo`), then adds extra simulated sessions (`scripts/generate_demo_data.py`)
so the dashboard has enough data to be meaningfully explored. Every record
this produces is flagged `is_demo=True` in the database and shown with a
`DEMO` badge in the dashboard.

## 15. Real ride workflow

```bash
python main.py --video data/input/my_ride.mp4 --gps data/input/my_ride.csv
python dashboard/app.py
```

Same pipeline, same code path as demo mode — just point it at real footage
and a real GPS log (see `core/gps_sync.py` docstring for the expected CSV
schema) and omit `--demo`.

## 16. ONNX export

```bash
python ml/export/export_onnx.py
```

Exports to ONNX, reports model size (PyTorch vs ONNX) and benchmarks CPU
inference latency for both. See `ml/export/export_report.json`.

## 17. Future Android architecture

Not implemented in V1. Full plan (what changes / what doesn't, concrete
steps): [`docs/android_deployment.md`](docs/android_deployment.md).

## 18. Installation

```bash
git clone <this repo>   # or just use the folder as-is
cd bari

# Windows
powershell -ExecutionPolicy Bypass -File setup_windows.ps1
# Linux/macOS
bash setup.sh
```

This installs **CPU-only PyTorch** by default to keep the install small —
see the script comments for switching to a CUDA build if you have a GPU and
disk headroom (a full CUDA PyTorch install is 2-3GB vs ~150MB for CPU-only).

Then:
```bash
python ml/datasets/prepare_dataset.py   # if not already run
python ml/datasets/validate_dataset.py
python scripts/run_demo.py
python dashboard/app.py
```

## 19. Commands reference

| Purpose | Command |
|---|---|
| Prepare dataset | `python ml/datasets/prepare_dataset.py` |
| Validate dataset | `python ml/datasets/validate_dataset.py` |
| Train | `python ml/training/train.py` |
| Evaluate | `python ml/evaluation/evaluate.py` |
| Single image/folder test | `python ml/inference/detect.py --source image.jpg` |
| Full video+GPS pipeline | `python main.py --video V.mp4 --gps G.csv` |
| Demo (end to end) | `python scripts/run_demo.py` |
| Generate demo GPS only | `python scripts/generate_demo_gps.py` |
| Generate demo video only | `python scripts/generate_demo_video.py` |
| Populate richer demo DB data | `python scripts/generate_demo_data.py` |
| ONNX export | `python ml/export/export_onnx.py` |
| Benchmark | `python scripts/benchmark.py --video data/input/demo_ride.mp4` |
| Export CSV | `python export_data.py --format csv` |
| Export JSON | `python export_data.py --format json` |
| Dashboard | `python dashboard/app.py` |
| Tests | `python -m pytest tests/ -q` |

## 20. Troubleshooting

- **`Model weights not found`** — train first (`ml/training/train.py`), or
  point `--weights` at a `.pt` file. `main.py`/`detect.py` will not fall
  back to a stock model silently.
- **Nominatim errors / rate limiting** — `core/geocoding.py` retries with
  backoff and caches results; if it still fails, location fields save as
  `"Unknown"` rather than crashing. Use `--no-geocode` on `main.py` /
  `generate_demo_data.py` for fully offline runs.
- **`CUDA not available`** — expected if you installed CPU-only PyTorch;
  the pipeline runs on CPU automatically (see `core/device.py`).
- **Dashboard shows no data** — run `scripts/run_demo.py` or point
  `main.py` at real input first; the dashboard only reflects what's in
  `data/bari.db`.
- **Windows `mp4v` codec warnings** — cosmetic; if playback is an issue,
  re-encode with ffmpeg (`ffmpeg -i in.mp4 -c:v libx264 out.mp4`).

## 21. Limitations

See [`docs/portfolio.md#limitations`](docs/portfolio.md#limitations) for
the full, honest list (dataset size, severity heuristic, zone boundaries
unavailable, demo video provenance, CPU-only inference, no Android yet).

## 22. Future roadmap

| Version | Scope |
|---|---|
| V1 (this repo) | Laptop video + GPS + ML + GIS + dashboard |
| V2 | ONNX optimization, larger dataset/model sweep |
| V3 | Android camera + GPS client |
| V4 | Offline Android operation |
| V5 | Cloud synchronization (`sync_queue` table already reserved) |
| V6 | Additional road-defect classes (cracks, waterlogging, debris) |

---

*Timestamps are ISO 8601, Asia/Kolkata. Severity is an estimated heuristic
in V1, not a professionally certified road-damage measurement.*
