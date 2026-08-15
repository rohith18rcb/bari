# BARI — Portfolio Writeup

## Project title

**BARI: Bengaluru AI Road Intelligence** — AI pothole detection, GPS mapping,
and road-condition analytics from dashcam-style video.

## Problem

Municipal road maintenance in a city the size of Bengaluru relies heavily on
manual reporting and periodic surveys. Potholes go unreported for weeks,
there's no systematic, geolocated record of where road damage clusters, and
there's no lightweight way to turn a simple dashcam ride into structured,
mappable data.

## Solution

BARI takes a road video and a synchronized GPS log (the same data a phone
naturally produces) and turns it into a set of confirmed, geolocated,
severity-scored pothole records: detected by a custom-trained YOLO model,
deduplicated via object tracking and GPS-proximity matching, located against
real Bengaluru ward boundaries and reverse geocoding, and visualized on an
interactive map with filterable analytics.

## Architecture

See [`docs/architecture.md`](architecture.md) for the full diagram. In short:

```
Video + GPS -> YOLO -> ByteTrack -> Event confirmation -> GPS sync
  -> Location resolution -> Severity heuristic -> Duplicate check
  -> SQLite -> Dashboard (map / analytics / export)
```

## ML approach

- **Model:** Ultralytics YOLOv8n, transfer-learned from COCO pretrained
  weights onto a single `pothole` class.
- **Tracking:** ByteTrack (via Ultralytics' built-in `model.track()`),
  chosen because it's a proven, dependency-light multi-object tracker that
  integrates natively with the YOLO inference loop — no separate
  re-identification model needed for this use case.
- **Event confirmation:** a track only becomes a database record once it
  has persisted for `MIN_TRACK_FRAMES` consecutive frames — this is a
  simple but effective filter against single-frame false positives *and*
  against counting one physical pothole dozens of times as the camera
  approaches it.

## Dataset

Real, licensed, non-fabricated: the Roboflow Universe
`project-ssayl/potholes-detection-d4rma` pothole dataset (CC BY 4.0), 300
images (100/100/100 train/valid/test), YOLO-txt annotated. Full provenance
recorded programmatically in `ml/datasets/processed/dataset_info.json`. See
[`docs/model_deployment.md`](model_deployment.md) for the honest limitations
of training on a dataset this size.

## Evaluation

Actual metrics (from `ml/evaluation/reports/evaluation_report.json`,
held-out test split, never seen during training):

```
Precision:   [INSERT ACTUAL PRECISION AFTER TRAINING]
Recall:      [INSERT ACTUAL RECALL AFTER TRAINING]
mAP@50:      [INSERT ACTUAL mAP50 AFTER TRAINING]
mAP@50-95:   [INSERT ACTUAL mAP50-95 AFTER TRAINING]
F1:          [INSERT ACTUAL F1 AFTER TRAINING]
Inference:   [INSERT ACTUAL ms/image AFTER TRAINING] (CPU)
```

*(This placeholder block is replaced with real numbers in the main README
once `ml/training/train.py` + `ml/evaluation/evaluate.py` finish running —
see the README for the current, filled-in values from this build.)*

## Engineering challenges

- **GPS/video synchronization without shared clock hardware.** Video frame
  N doesn't inherently know its wall-clock time. `core/gps_sync.py` treats
  this as a time-series alignment problem: nearest-neighbor lookup with
  linear interpolation between bracketing GPS samples, a configurable
  offset for clock drift, and explicit handling for GPS dropouts and
  before/after-track edge cases — rather than the common shortcut of
  "use the first GPS row for everything."
- **Not double-counting one pothole.** Solved at two levels: object
  tracking + persistence-threshold confirmation (same pothole, same pass)
  and GPS-proximity + time-window matching against the database (same
  pothole, different pass/session) — see `core/duplicate.py`. Ambiguous
  matches are labeled `POSSIBLE_DUPLICATE` rather than silently merged.
- **Real Bengaluru geography without fabricating boundaries.** Rather than
  invent ward/zone polygons, the project sources real BBMP ward boundary
  GeoJSON (243 wards, CC BY-SA 2.5 IN, from the datameet open-data
  community) for point-in-polygon ward resolution, and is honest that no
  equivalent zone-boundary open dataset was found — zone resolves to
  `"Unknown"` rather than a fabricated value (see
  `data/bengaluru/README.md`).
- **Reverse geocoding without violating usage limits or blocking the
  pipeline.** `core/geocoding.py` only geocodes *confirmed* events (not
  every frame), rate-limits and caches (in-memory and DB-persisted) calls
  to Nominatim, retries with backoff, and degrades to `"Unknown"` fields
  rather than crashing if the network/provider is unavailable.
- **Fitting the whole stack in ~7GB of free disk.** Chose CPU-only PyTorch,
  opencv-python-headless, and a modestly-sized (~20MB) real dataset instead
  of a much larger one, so training/evaluation could actually complete in
  this environment — documented explicitly rather than silently degraded.

## Results

See the main [README](../README.md) for this build's actual recorded
metrics, dataset size, and demo instructions — all pulled from real
executed runs, never invented.

## Limitations

- Small training dataset (300 images, 1 class) — narrow generalization.
- Severity is a transparent geometric heuristic (box area + persistence),
  not a validated road-engineering measurement.
- GPS accuracy depends entirely on the input device; low-accuracy fixes are
  flagged, not corrected.
- Zone resolution is unavailable (`"Unknown"`) without a user-supplied
  zone-boundary GeoJSON.
- No real Bengaluru dashcam footage was used in this build — the shipped
  demo video is a labeled synthetic composite (see `scripts/generate_demo_video.py`);
  the *pipeline itself* is fully real and works identically on genuine footage.
- CPU-only inference in this build. A native Android app captures and
  uploads real photos (shipped, verified end-to-end), but detection itself
  still runs server-side — fully on-device inference is future work.

## Future improvements

1. Train on a larger, more diverse pothole dataset (multiple weather/lighting
   conditions, multiple cities) with a bigger backbone (yolov8s/m) on GPU.
2. Add a proper zone-boundary GeoJSON once a legitimately licensed one is
   located or produced.
3. Replace the severity heuristic with a learned regressor once enough
   human-labeled severity ground truth exists.
4. Android on-device client (see `docs/android_deployment.md`).
5. Cloud sync + multi-contributor aggregation (the `sync_queue` table is
   already reserved for this).

## Resume bullet suggestions

- "Built an end-to-end computer vision pipeline (YOLOv8 + ByteTrack) that
  detects and geolocates road potholes from video + GPS, with custom GPS
  timestamp-interpolation logic, real GIS boundary resolution, and a
  FastAPI + Leaflet analytics dashboard."
- "Designed a two-level duplicate-detection system combining object
  tracking (same-pass) and GPS-proximity matching (cross-session) to avoid
  overcounting recurring detections in a geospatial ML pipeline."
- "Trained and evaluated a custom YOLOv8 object detector on a licensed
  dataset, with a full data-validation, training, evaluation, and ONNX
  export pipeline runnable end-to-end from the CLI."

## Interview questions this project could prompt

- "Why ByteTrack instead of just deduplicating by IoU across frames?"
- "How do you synchronize two independently-sampled time series (video
  frames and GPS fixes) without a shared clock?"
- "Walk me through what happens when GPS accuracy is poor or a GPS sample is
  missing entirely — does the pipeline still produce a record?"
- "How would you tell the difference between the same pothole seen twice
  versus two different potholes 5 meters apart?"
- "Why store timestamps as ISO8601 strings instead of native SQL DATETIME?"
- "What would change if this had to run on-device on Android instead of a
  laptop?"
- "How did you decide severity was a heuristic and not a trained model —
  what would it take to make it one?"
