from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
CLEAN_PATH = ROOT / "calcofi_relevant.csv"
OUTPUT_PATH = ROOT / "mooring_replay.csv"

# A historical California Current heatwave slice that gives us
# a clear, chronologically coherent anomaly replay for the demo.
EVENT_START = "2015-10-29 00:00:00"
EVENT_END = "2015-10-31 23:59:59"
RESAMPLE_INTERVAL = "1h"


def load_clean_frame():
    df = pd.read_csv(CLEAN_PATH, parse_dates=["timestamp"])
    df = df[df["station_lat"].between(27, 38) & df["station_lon"].between(-125, -115)].copy()
    df = df[df["dissolved_oxygen"].between(0, 15)].copy()
    return df


def aggregate_observations(df: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        df.groupby(["timestamp", "station_lat", "station_lon"], as_index=False)
        .agg(
            {
                "temp_c": "mean",
                "salinity": "mean",
                "dissolved_oxygen": "mean",
            }
        )
        .sort_values("timestamp")
    )
    return grouped


def select_event_window(df: pd.DataFrame) -> pd.DataFrame:
    window = df[(df["timestamp"] >= EVENT_START) & (df["timestamp"] <= EVENT_END)].copy()
    if window.empty:
        raise ValueError("No replay rows found for the selected event window.")
    return window.sort_values("timestamp")


def resample_window(window: pd.DataFrame) -> pd.DataFrame:
    numeric_cols = ["temp_c", "salinity", "dissolved_oxygen", "station_lat", "station_lon"]
    series = window.set_index("timestamp")[numeric_cols].sort_index()

    grid = pd.date_range(
        series.index.min().floor(RESAMPLE_INTERVAL),
        series.index.max().ceil(RESAMPLE_INTERVAL),
        freq=RESAMPLE_INTERVAL,
    )

    replay = (
        series.reindex(series.index.union(grid))
        .sort_index()
        .interpolate(method="time")
        .loc[grid]
        .reset_index()
        .rename(columns={"index": "timestamp"})
    )
    return replay


def finalize_replay(replay: pd.DataFrame) -> pd.DataFrame:
    replay = replay.copy()
    replay = replay.dropna(subset=["temp_c", "salinity", "dissolved_oxygen", "station_lat", "station_lon"])
    replay["temp_c"] = replay["temp_c"].round(3)
    replay["salinity"] = replay["salinity"].round(3)
    replay["dissolved_oxygen"] = replay["dissolved_oxygen"].round(3)
    replay["station_lat"] = replay["station_lat"].round(5)
    replay["station_lon"] = replay["station_lon"].round(5)
    replay["timestamp"] = replay["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    return replay[
        [
            "timestamp",
            "temp_c",
            "salinity",
            "dissolved_oxygen",
            "station_lat",
            "station_lon",
        ]
    ]


def main():
    print("Loading cleaned CalCOFI observations...")
    df = load_clean_frame()
    grouped = aggregate_observations(df)
    window = select_event_window(grouped)
    replay = finalize_replay(resample_window(window))

    replay.to_csv(OUTPUT_PATH, index=False)
    print(f"Wrote replay file: {OUTPUT_PATH} ({len(replay):,} rows)")
    print("First rows:")
    print(replay.head(5).to_string(index=False))
    print("\nLast rows:")
    print(replay.tail(5).to_string(index=False))


if __name__ == "__main__":
    main()
