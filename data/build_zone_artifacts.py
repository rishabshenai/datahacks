from __future__ import annotations

from pathlib import Path

import json

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
CLEAN_PATH = ROOT / "calcofi_relevant.csv"
GLOBAL_BASELINES_PATH = ROOT / "baselines.json"
ZONE_BASELINES_PATH = ROOT / "zone_baselines.json"
ZONE_REPLAYS_PATH = ROOT / "zone_replays.json"

ZONE_CONFIG = {
    "del-mar": {
        "label": "Del Mar",
        "lat": 32.96,
        "lon": -117.28,
        "radius_deg": 0.08,
    },
    "point-loma": {
        "label": "Point Loma",
        "lat": 32.66,
        "lon": -117.25,
        "radius_deg": 0.12,
    },
    "south-bay": {
        "label": "South Bay",
        "lat": 32.56,
        "lon": -117.17,
        "radius_deg": 0.15,
    },
}

TARGET_START = pd.Timestamp("2024-04-01 09:00:00")
TARGET_PERIODS = 36
TARGET_FREQ = "10min"
RADIUS_OFFSETS = [0.0, 0.05, 0.10, 0.15, 0.20]


def load_clean_frame() -> pd.DataFrame:
    df = pd.read_csv(CLEAN_PATH, parse_dates=["timestamp"])
    df = df[df["dissolved_oxygen"].between(0, 15)].copy()
    return df


def load_global_baselines() -> dict[int, dict]:
    raw = json.loads(GLOBAL_BASELINES_PATH.read_text())
    if isinstance(raw, dict):
        raw = [{"month": int(month), **values} for month, values in raw.items()]
    return {int(row["month"]): row for row in raw}


def zone_subset(df: pd.DataFrame, cfg: dict, radius: float | None = None) -> pd.DataFrame:
    radius = cfg["radius_deg"] if radius is None else radius
    sub = df[
        df["station_lat"].between(cfg["lat"] - radius, cfg["lat"] + radius)
        & df["station_lon"].between(cfg["lon"] - radius, cfg["lon"] + radius)
    ].copy()
    return sub


def safe_stats(series: pd.Series):
    values = series.dropna()
    if values.empty:
        return None, None
    std = float(values.std())
    if pd.isna(std) or std == 0:
        std = 1e-6
    return round(float(values.mean()), 4), round(std, 4)


def build_zone_baselines(df: pd.DataFrame, cfg: dict, zone_name: str, global_baselines: dict[int, dict]) -> list[dict]:
    rows = []
    for month in range(1, 13):
        temp_mean = temp_std = sal_mean = sal_std = oxygen_mean = oxygen_std = None
        source = "global"
        radius_used = None

        for offset in RADIUS_OFFSETS:
            radius = cfg["radius_deg"] + offset
            month_df = zone_subset(df, cfg, radius=radius)
            month_df = month_df[month_df["timestamp"].dt.month == month]
            temp_mean, temp_std = safe_stats(month_df["temp_c"])
            sal_mean, sal_std = safe_stats(month_df["salinity"])
            oxygen_mean, oxygen_std = safe_stats(month_df["dissolved_oxygen"])
            if all(value is not None for value in [temp_mean, temp_std, sal_mean, sal_std, oxygen_mean, oxygen_std]):
                source = "zone" if offset == 0 else "expanded-zone"
                radius_used = round(radius, 3)
                break

        if any(value is None for value in [temp_mean, temp_std, sal_mean, sal_std, oxygen_mean, oxygen_std]):
            global_row = global_baselines[month]
            temp_mean = global_row["temp_mean"]
            temp_std = global_row["temp_std"]
            sal_mean = global_row["sal_mean"]
            sal_std = global_row["sal_std"]
            oxygen_mean = global_row["oxygen_mean"]
            oxygen_std = global_row["oxygen_std"]

        rows.append(
            {
                "zone": zone_name,
                "month": month,
                "temp_mean": temp_mean,
                "temp_std": temp_std,
                "sal_mean": sal_mean,
                "sal_std": sal_std,
                "oxygen_mean": oxygen_mean,
                "oxygen_std": oxygen_std,
                "source": source,
                "radius_deg_used": radius_used,
            }
        )
    return rows


def zscore(value: float, mean: float | None, std: float | None) -> float:
    if mean is None or std in (None, 0):
        return 0.0
    return (value - mean) / std


def aggregate_zone_observations(zone_df: pd.DataFrame) -> pd.DataFrame:
    return (
        zone_df.groupby(["timestamp", "station_lat", "station_lon"], as_index=False)
        .agg(
            {
                "temp_c": "mean",
                "salinity": "mean",
                "dissolved_oxygen": "mean",
            }
        )
        .sort_values("timestamp")
        .reset_index(drop=True)
    )


def baseline_lookup(baselines: list[dict]) -> dict[int, dict]:
    return {int(row["month"]): row for row in baselines}


def select_zone_event(agg: pd.DataFrame, baselines: list[dict]) -> pd.DataFrame:
    base_by_month = baseline_lookup(baselines)
    working = agg.copy()
    working["month"] = working["timestamp"].dt.month
    working["temp_z"] = working.apply(
        lambda row: zscore(row["temp_c"], base_by_month[row["month"]]["temp_mean"], base_by_month[row["month"]]["temp_std"]),
        axis=1,
    )
    working["sal_z"] = working.apply(
        lambda row: zscore(row["salinity"], base_by_month[row["month"]]["sal_mean"], base_by_month[row["month"]]["sal_std"]),
        axis=1,
    )
    working["oxygen_z"] = working.apply(
        lambda row: zscore(
            row["dissolved_oxygen"],
            base_by_month[row["month"]]["oxygen_mean"],
            base_by_month[row["month"]]["oxygen_std"],
        ),
        axis=1,
    )
    working["stress"] = (
        working["temp_z"].clip(lower=0)
        + (-working["oxygen_z"]).clip(lower=0)
        + 0.5 * working["sal_z"].abs()
    )

    peak_idx = int(working["stress"].idxmax())
    start = max(0, peak_idx - 4)
    end = min(len(working), peak_idx + 5)
    window = working.iloc[start:end].copy()
    if len(window) < 5:
        window = working.nlargest(min(8, len(working)), "stress").sort_values("timestamp").copy()
    return window


def inject_anomaly_pulse(replay: pd.DataFrame, event_df: pd.DataFrame, baselines: list[dict]) -> pd.DataFrame:
    month_baseline = baseline_lookup(baselines)[TARGET_START.month]
    center = (len(replay) - 1) / 2
    sigma = max(len(replay) / 7, 2)
    weights = np.exp(-0.5 * ((np.arange(len(replay)) - center) / sigma) ** 2)

    hot_row = event_df.loc[event_df["temp_z"].idxmax()]
    low_oxygen_row = event_df.loc[event_df["oxygen_z"].idxmin()]
    sal_row = event_df.loc[event_df["sal_z"].abs().idxmax()]

    temp_delta = max(float(hot_row["temp_c"]) - month_baseline["temp_mean"], 0.0)
    oxygen_delta = min(float(low_oxygen_row["dissolved_oxygen"]) - month_baseline["oxygen_mean"], 0.0)
    sal_delta = float(sal_row["salinity"]) - month_baseline["sal_mean"]

    replay = replay.copy()
    replay["temp_c"] += weights * temp_delta * 0.9
    replay["dissolved_oxygen"] += weights * oxygen_delta * 1.1
    replay["salinity"] += weights * sal_delta * 0.7
    return replay


def normalize_event_to_shared_timeline(event_df: pd.DataFrame, cfg: dict, baselines: list[dict]) -> list[dict]:
    event_df = event_df.sort_values("timestamp").copy()
    relative_hours = (event_df["timestamp"] - event_df["timestamp"].min()) / pd.Timedelta(hours=1)
    event_df["relative_hour"] = relative_hours

    target_hours = pd.Series(range(TARGET_PERIODS), dtype=float)
    scale = max(float(event_df["relative_hour"].max()), 1.0) / max(float(target_hours.max()), 1.0)
    target_relative = target_hours * scale

    replay = pd.DataFrame({"relative_hour": target_relative})
    for column in ["temp_c", "salinity", "dissolved_oxygen", "station_lat", "station_lon"]:
        replay[column] = (
            event_df.set_index("relative_hour")[column]
            .reindex(event_df["relative_hour"].sort_values().unique())
            .interpolate(method="index")
            .reindex(target_relative, method=None)
            .interpolate(method="index")
            .to_numpy()
        )

    replay["timestamp"] = pd.date_range(TARGET_START, periods=TARGET_PERIODS, freq=TARGET_FREQ)
    replay["zone"] = cfg["label"]
    replay = inject_anomaly_pulse(replay, event_df, baselines)
    replay = replay.drop(columns=["relative_hour"])
    replay["temp_c"] = replay["temp_c"].round(3)
    replay["salinity"] = replay["salinity"].round(3)
    replay["dissolved_oxygen"] = replay["dissolved_oxygen"].round(3)
    replay["station_lat"] = replay["station_lat"].round(5)
    replay["station_lon"] = replay["station_lon"].round(5)
    replay["timestamp"] = replay["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    return replay.to_dict(orient="records")


def main():
    print("Loading cleaned CalCOFI data...")
    df = load_clean_frame()
    global_baselines = load_global_baselines()

    zone_baselines: dict[str, list[dict]] = {}
    zone_replays: dict[str, list[dict]] = {}

    for zone_name, cfg in ZONE_CONFIG.items():
        zone_df = zone_subset(df, cfg)
        if zone_df.empty:
            raise ValueError(f"No CalCOFI rows found for zone {zone_name}.")

        baselines = build_zone_baselines(df, cfg, zone_name, global_baselines)
        zone_baselines[zone_name] = baselines

        aggregated = aggregate_zone_observations(zone_df)
        event_df = select_zone_event(aggregated, baselines)
        zone_replays[zone_name] = normalize_event_to_shared_timeline(event_df, cfg, baselines)

        print(
            f"{zone_name}: "
            f"{len(zone_df):,} raw rows, "
            f"{len(aggregated):,} aggregated rows, "
            f"{len(zone_replays[zone_name]):,} replay steps"
        )

    ZONE_BASELINES_PATH.write_text(json.dumps(zone_baselines, indent=2))
    ZONE_REPLAYS_PATH.write_text(json.dumps(zone_replays, indent=2))
    print(f"Wrote zone baselines: {ZONE_BASELINES_PATH}")
    print(f"Wrote zone replays:   {ZONE_REPLAYS_PATH}")


if __name__ == "__main__":
    main()
