from __future__ import annotations

from pathlib import Path

import json

import joblib
import pandas as pd
from sklearn.ensemble import IsolationForest


ROOT = Path(__file__).resolve().parent
CLEAN_PATH = ROOT / "calcofi_relevant.csv"
ZONE_BASELINES_PATH = ROOT / "zone_baselines.json"
ZONE_MODELS_PATH = ROOT / "zone_models.pkl"

ZONE_CONFIG = {
    "del-mar": {"lat": 32.96, "lon": -117.28, "radius_deg": 0.08},
    "point-loma": {"lat": 32.66, "lon": -117.25, "radius_deg": 0.12},
    "south-bay": {"lat": 32.56, "lon": -117.17, "radius_deg": 0.15},
}

NORMAL_CORE_SIGMA = 0.9
MODEL_CONTAMINATION = 0.2


def load_clean_frame() -> pd.DataFrame:
    df = pd.read_csv(CLEAN_PATH, parse_dates=["timestamp"])
    df = df[df["dissolved_oxygen"].between(0, 15)].copy()
    df = df.dropna(subset=["timestamp", "temp_c", "salinity", "dissolved_oxygen"])
    return df


def load_zone_baselines() -> dict[str, dict[int, dict]]:
    raw = json.loads(ZONE_BASELINES_PATH.read_text())
    return {
        zone: {int(row["month"]): row for row in rows}
        for zone, rows in raw.items()
    }


def zscore(value: float, mean: float | None, std: float | None) -> float:
    if mean is None or std in (None, 0):
        return 0.0
    return (value - mean) / std


def zone_subset(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    radius = cfg["radius_deg"]
    return df[
        df["station_lat"].between(cfg["lat"] - radius, cfg["lat"] + radius)
        & df["station_lon"].between(cfg["lon"] - radius, cfg["lon"] + radius)
    ].copy()


def feature_frame(zone_df: pd.DataFrame, baselines: dict[int, dict]) -> pd.DataFrame:
    working = zone_df.copy()
    working["month"] = working["timestamp"].dt.month
    working["temp_z"] = working.apply(
        lambda row: zscore(row["temp_c"], baselines[row["month"]]["temp_mean"], baselines[row["month"]]["temp_std"]),
        axis=1,
    )
    working["sal_z"] = working.apply(
        lambda row: zscore(row["salinity"], baselines[row["month"]]["sal_mean"], baselines[row["month"]]["sal_std"]),
        axis=1,
    )
    working["oxygen_z"] = working.apply(
        lambda row: zscore(
            row["dissolved_oxygen"],
            baselines[row["month"]]["oxygen_mean"],
            baselines[row["month"]]["oxygen_std"],
        ),
        axis=1,
    )
    return working[["temp_z", "sal_z", "oxygen_z"]].replace([float("inf"), float("-inf")], pd.NA).dropna()


def trim_features(features: pd.DataFrame) -> pd.DataFrame:
    trimmed = features[
        features["temp_z"].abs().le(NORMAL_CORE_SIGMA)
        & features["sal_z"].abs().le(NORMAL_CORE_SIGMA)
        & features["oxygen_z"].abs().le(NORMAL_CORE_SIGMA)
    ].copy()
    return trimmed if not trimmed.empty else features


def train_model(features: pd.DataFrame) -> IsolationForest:
    model = IsolationForest(
        n_estimators=250,
        contamination=MODEL_CONTAMINATION,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(features[["temp_z", "sal_z", "oxygen_z"]])
    return model


def main():
    print("Training zone-specific isolation forests...")
    clean = load_clean_frame()
    baselines = load_zone_baselines()

    models = {}
    summary = {}
    for zone_name, cfg in ZONE_CONFIG.items():
        zone_df = zone_subset(clean, cfg)
        features = feature_frame(zone_df, baselines[zone_name])
        trimmed = trim_features(features)
        models[zone_name] = train_model(trimmed)
        summary[zone_name] = {
            "raw_rows": int(len(zone_df)),
            "feature_rows": int(len(features)),
            "train_rows": int(len(trimmed)),
        }

    joblib.dump(models, ZONE_MODELS_PATH)
    print(json.dumps(summary, indent=2))
    print(f"Wrote zone models: {ZONE_MODELS_PATH}")


if __name__ == "__main__":
    main()
