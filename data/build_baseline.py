from pathlib import Path

import json

import pandas as pd


ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "CalCOFI_Database_194903-202105_csv_16October2023" / "CalCOFI_Database_194903-202105_csv_16October2023"
BOTTLE_PATH = RAW_DIR / "194903-202105_Bottle.csv"
CAST_PATH = RAW_DIR / "194903-202105_Cast.csv"
CLEAN_PATH = ROOT / "calcofi_relevant.csv"
BASELINE_PATH = ROOT / "baselines.json"


def load_raw_frames():
    bottle = pd.read_csv(
        BOTTLE_PATH,
        usecols=["Cst_Cnt", "Sta_ID", "Depthm", "T_degC", "Salnty", "O2ml_L", "Oxy_µmol/Kg", "pH1", "pH2"],
        low_memory=False,
        encoding="latin-1",
    )
    cast = pd.read_csv(
        CAST_PATH,
        usecols=["Cst_Cnt", "Sta_ID", "Date", "Time", "Month", "Lat_Dec", "Lon_Dec"],
        low_memory=False,
        encoding="latin-1",
    )
    return bottle, cast


def build_clean_frame():
    bottle, cast = load_raw_frames()

    cast = cast.drop_duplicates(subset=["Cst_Cnt"])
    merged = bottle.merge(cast, on="Cst_Cnt", how="left", suffixes=("", "_cast"), validate="many_to_one")

    merged["timestamp"] = pd.to_datetime(
        merged["Date"].astype(str) + " " + merged["Time"].fillna("00:00:00").astype(str),
        format="%m/%d/%Y %H:%M:%S",
        errors="coerce",
    )
    merged["month"] = merged["Month"].fillna(merged["timestamp"].dt.month)
    merged["dissolved_oxygen"] = merged["O2ml_L"].combine_first(merged["Oxy_µmol/Kg"])
    merged["ph"] = merged["pH1"].combine_first(merged["pH2"])

    clean = merged.rename(
        columns={
            "T_degC": "temp_c",
            "Salnty": "salinity",
            "Lat_Dec": "station_lat",
            "Lon_Dec": "station_lon",
        }
    )[
        [
            "timestamp",
            "month",
            "Cst_Cnt",
            "Sta_ID",
            "Depthm",
            "temp_c",
            "salinity",
            "dissolved_oxygen",
            "ph",
            "station_lat",
            "station_lon",
        ]
    ]

    clean = clean[clean["Depthm"] < 200].copy()
    clean = clean.dropna(subset=["timestamp", "temp_c", "salinity"])
    clean["month"] = clean["month"].astype(int)
    return clean


def safe_stats(series):
    values = series.dropna()
    if values.empty:
        return None, None
    return round(float(values.mean()), 4), round(float(values.std()), 4)


def build_baselines(clean):
    rows = []
    for month in range(1, 13):
        month_df = clean[clean["month"] == month]
        temp_mean, temp_std = safe_stats(month_df["temp_c"])
        sal_mean, sal_std = safe_stats(month_df["salinity"])
        oxygen_mean, oxygen_std = safe_stats(month_df["dissolved_oxygen"])
        ph_mean, ph_std = safe_stats(month_df["ph"])

        rows.append(
            {
                "month": month,
                "temp_mean": temp_mean,
                "temp_std": temp_std,
                "sal_mean": sal_mean,
                "sal_std": sal_std,
                "oxygen_mean": oxygen_mean,
                "oxygen_std": oxygen_std,
                "ph_mean": ph_mean,
                "ph_std": ph_std,
            }
        )
    return rows


def main():
    print("Loading and cleaning CalCOFI bottle/cast data...")
    clean = build_clean_frame()
    CLEAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    clean.to_csv(CLEAN_PATH, index=False)
    print(f"Wrote cleaned dataset: {CLEAN_PATH} ({len(clean):,} rows)")

    baselines = build_baselines(clean)
    with open(BASELINE_PATH, "w") as f:
        json.dump(baselines, f, indent=2)
    print(f"Wrote monthly baselines: {BASELINE_PATH}")

    sample = [row for row in baselines if row["temp_mean"] is not None][:2]
    print("Sample baseline rows:")
    print(json.dumps(sample, indent=2))


if __name__ == "__main__":
    main()
