#!/usr/bin/env python3
"""
generate_splats.py — EasyOneArgo → splats.json
Aegis Ocean  |  DataHacks 2026

Usage:
    python data/generate_splats.py [--output frontend/splats.json] [--synthetic]

Requirements:
    pip install argopy numpy

The script first tries to pull real Argo float profiles from Scripps/ERDDAP.
If the network call fails (or --synthetic is passed), it falls back to a
high-quality synthetic dataset derived from CalCOFI 75-year climatology for
the California Current region.  Either path produces a valid splats.json that
the Three.js scene can load immediately.
"""

import argparse
import json
import math
import numpy as np
import os
import random
import sys
import time

# ── CLI args ────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument(
    "--output",
    default=os.path.join(os.path.dirname(__file__), "..", "frontend", "splats.json"),
    help="Output path for splats.json (default: frontend/splats.json)",
)
parser.add_argument(
    "--synthetic",
    action="store_true",
    help="Skip Argo network fetch; generate synthetic California Current data",
)
parser.add_argument(
    "--max-splats",
    type=int,
    default=30000,
    help="Cap total splat count (default 30 000 for smooth 60fps)",
)
args = parser.parse_args()

OUTPUT_PATH = os.path.abspath(args.output)
os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

# California Current surface baseline (CalCOFI 75-yr mean)
TEMP_BASELINE = 15.0   # °C
TEMP_STD      = 2.5    # °C

# ── OPTION A: real Argo data ────────────────────────────────────────────────
def fetch_argo_splats(max_splats: int) -> list[dict]:
    """
    Fetches California Current profile data via argopy (Scripps ERDDAP).
    Region: lon -135→-110, lat 20→50, depth 0→2000m, 2020-01→2024-01
    """
    import argopy                                         # noqa: PLC0415

    print("Connecting to Scripps ERDDAP (argopy) … this may take 60-90 s")
    loader = argopy.DataFetcher(src="erddap").region(
        [-135, -110, 20, 50, 0, 2000, "2020-01", "2024-01"]
    )
    ds = loader.to_xarray()
    print(f"  Fetched {len(ds.N_PROF)} profiles, {len(ds.N_LEVELS)} depth levels")

    splats = []
    for i in range(len(ds.N_PROF)):
        lon = float(ds.LONGITUDE[i])
        lat = float(ds.LATITUDE[i])
        for j in range(len(ds.N_LEVELS)):
            depth = float(ds.PRES[i, j])
            if depth > 2000:
                continue
            temp_raw = ds.TEMP[i, j]
            sal_raw  = ds.PSAL[i, j]
            temp = float(temp_raw) if not np.isnan(temp_raw) else None
            sal  = float(sal_raw)  if not np.isnan(sal_raw)  else None
            if temp is None:
                continue
            splats.append(
                {
                    "x": round((lon + 180) / 360 * 2 - 1, 5),   # -1 → 1
                    "y": round((lat + 90)  / 180 * 2 - 1, 5),   # -1 → 1
                    "z": round(-(depth / 2000), 5),              #  0 → -1
                    "temp": round(temp, 2),
                    "sal":  round(sal, 2) if sal else None,
                    "anomaly": round(
                        np.clip((temp - TEMP_BASELINE) / (TEMP_STD * 2), -1, 1), 4
                    ),
                    "scale": round(
                        0.004 + (1 / max(len(ds.N_PROF) ** 0.5, 1)) * 0.01, 5
                    ),
                }
            )
            if len(splats) >= max_splats:
                return splats
    return splats


# ── OPTION B: synthetic California Current ──────────────────────────────────
def synthetic_splats(n: int = 25000) -> list[dict]:
    """
    Generates a physically plausible synthetic point cloud for the California
    Current region based on CalCOFI 75-year climatological averages.

    Thermal structure:
      - Surface (0-50m):  mean 16°C, decreases with latitude North
      - Thermocline:      sharp drop between 50-200m
      - Deep (>200m):     cold (5-8°C), nearly uniform
    Anomalies:
      - "Blob" marine heatwave patches randomly placed near surface
      - Upwelling cold tongues along coast (lon ~-117 to -120)
    """
    print(f"Generating {n:,} synthetic California Current splats …")
    rng = random.Random(42)
    np_rng = np.random.default_rng(42)

    # Geographic bounds (California Current bounding box)
    LON_MIN, LON_MAX = -135, -110
    LAT_MIN, LAT_MAX =   20,   50

    # Random marine heatwave patches (1-3 surface blobs)
    n_blobs = rng.randint(1, 3)
    blobs = [
        {
            "cx": rng.uniform(-128, -115),
            "cy": rng.uniform(28, 45),
            "r":  rng.uniform(3, 8),   # degrees
            "dt": rng.uniform(2, 4),   # ΔT above baseline
        }
        for _ in range(n_blobs)
    ]

    splats = []
    for _ in range(n):
        lon   = np_rng.uniform(LON_MIN, LON_MAX)
        lat   = np_rng.uniform(LAT_MIN, LAT_MAX)
        depth = np_rng.exponential(scale=200)   # more surface samples
        depth = min(depth, 2000)

        # Depth-based temperature profile (simplified)
        if depth < 50:
            base_t = 17.5 - (lat - 30) * 0.12    # warmer south, cooler north
        elif depth < 200:
            # Thermocline
            frac   = (depth - 50) / 150
            base_t = (17.5 - (lat - 30) * 0.12) * (1 - frac) + 8.0 * frac
        else:
            base_t = 8.0 - (depth - 200) / 1800 * 3.0   # slight cooling

        # Upwelling cold tongue along coast
        coast_dist = lon - (-120)   # positive = offshore
        if coast_dist < 3 and depth < 100:
            base_t -= 2.5 * max(0, (3 - coast_dist) / 3)

        # Marine heatwave blob influence (surface only)
        if depth < 100:
            for b in blobs:
                dist = math.sqrt((lon - b["cx"]) ** 2 + (lat - b["cy"]) ** 2)
                if dist < b["r"]:
                    base_t += b["dt"] * (1 - dist / b["r"]) * (1 - depth / 100)

        # Add noise
        temp = base_t + np_rng.normal(0, 0.6)
        sal  = round(33.5 + np_rng.normal(0, 0.3), 2)

        anomaly = float(np.clip((temp - TEMP_BASELINE) / (TEMP_STD * 2), -1, 1))

        splats.append(
            {
                "x": round((lon + 180) / 360 * 2 - 1, 5),
                "y": round((lat + 90)  / 180 * 2 - 1, 5),
                "z": round(-(depth / 2000), 5),
                "temp": round(float(temp), 2),
                "sal":  sal,
                "anomaly": round(anomaly, 4),
                "scale": round(0.004 + np_rng.uniform(0, 0.003), 5),
            }
        )
    return splats


# ── MAIN ────────────────────────────────────────────────────────────────────
def main():
    splats = None

    if not args.synthetic:
        try:
            splats = fetch_argo_splats(args.max_splats)
            print(f"  ✓ Real Argo data: {len(splats):,} splats")
        except Exception as exc:
            print(f"  ✗ Argo fetch failed ({exc})")
            print("    → Falling back to synthetic CalCOFI-region data")

    if splats is None:
        splats = synthetic_splats(min(args.max_splats, 25000))
        print(f"  ✓ Synthetic data: {len(splats):,} splats")

    out_path = OUTPUT_PATH
    print(f"Writing {len(splats):,} splats → {out_path}")
    with open(out_path, "w") as f:
        json.dump(splats, f, separators=(",", ":"))   # compact JSON

    size_mb = os.path.getsize(out_path) / 1_048_576
    print(f"Done. File size: {size_mb:.1f} MB")
    print()
    print("Next steps:")
    print("  1. Open frontend/index.html in a browser — it will auto-load splats.json")
    print("     from the same directory via fetch('./splats.json').")
    print("  2. When ready, upload to S3:")
    print("     aws s3 cp frontend/splats.json s3://aegis-ocean-data/splats.json --acl public-read")
    print("  3. Update the fetch URL in index.html to point at the S3 public URL.")


if __name__ == "__main__":
    main()
