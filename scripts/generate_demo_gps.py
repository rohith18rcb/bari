"""
generate_demo_gps.py — simulates a GPS track along a driving route through
several well-known Bengaluru localities, for demo purposes only.

IMPORTANT: These are SIMULATED route points for demonstration, not real
collected GPS observations. Waypoint coordinates are approximate public
locality centers, used only to give the demo a recognizable, geographically
plausible Bengaluru route (Majestic -> Shivajinagar -> Indiranagar ->
KR Puram -> Whitefield).

Usage:
    python scripts/generate_demo_gps.py --duration 120 --out data/input/demo_ride.csv
"""
from __future__ import annotations

import argparse
import csv
import logging
import random
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("bari.generate_demo_gps")

IST = ZoneInfo("Asia/Kolkata")

# Approximate public locality centers (simulated route waypoints — NOT precise survey data)
WAYPOINTS = [
    ("Majestic", 12.9767, 77.5713),
    ("Shivajinagar", 12.9857, 77.6057),
    ("Indiranagar", 12.9784, 77.6408),
    ("KR Puram", 13.0088, 77.6970),
    ("Whitefield", 12.9698, 77.7500),
]


def generate_track(duration_seconds: int, hz: float, start_time: datetime, seed: int) -> list[dict]:
    rng = random.Random(seed)
    n_points = max(int(duration_seconds * hz), 2)
    segments = len(WAYPOINTS) - 1
    points = []

    for i in range(n_points):
        progress = i / (n_points - 1)  # 0..1 across the whole route
        seg_progress = progress * segments
        seg_idx = min(int(seg_progress), segments - 1)
        local_t = seg_progress - seg_idx

        _, lat1, lon1 = WAYPOINTS[seg_idx]
        _, lat2, lon2 = WAYPOINTS[seg_idx + 1]
        lat = lat1 + (lat2 - lat1) * local_t
        lon = lon1 + (lon2 - lon1) * local_t

        # small realistic jitter (consumer GPS noise)
        lat += rng.uniform(-0.00004, 0.00004)
        lon += rng.uniform(-0.00004, 0.00004)
        accuracy = round(rng.uniform(3.0, 12.0), 1)
        speed = round(rng.uniform(6.0, 14.0), 1)  # m/s ~ 22-50 km/h city driving

        import math
        bearing = (math.degrees(math.atan2(lon2 - lon1, lat2 - lat1)) + 360) % 360
        bearing = round((bearing + rng.uniform(-4, 4)) % 360, 1)

        ts = start_time + timedelta(seconds=i / hz)
        points.append({
            "timestamp": ts.isoformat(),
            "latitude": round(lat, 6),
            "longitude": round(lon, 6),
            "accuracy": accuracy,
            "speed": speed,
            "bearing": bearing,
        })

    return points


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a simulated Bengaluru GPS route for demo purposes")
    parser.add_argument("--duration", type=int, default=120, help="Route duration in seconds")
    parser.add_argument("--hz", type=float, default=1.0, help="GPS sample rate")
    parser.add_argument("--out", type=Path, default=Path("data/input/demo_ride.csv"))
    parser.add_argument("--start-time", type=str, default=None, help="ISO8601 start time; defaults to now (IST)")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    start_time = datetime.fromisoformat(args.start_time) if args.start_time else datetime.now(IST)
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=IST)

    points = generate_track(args.duration, args.hz, start_time, args.seed)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "latitude", "longitude", "accuracy", "speed", "bearing"])
        writer.writeheader()
        writer.writerows(points)

    route_names = " -> ".join(w[0] for w in WAYPOINTS)
    logger.info("Simulated GPS route [DEMO DATA] written: %s (%d points, %ds, route: %s)",
                args.out, len(points), args.duration, route_names)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
