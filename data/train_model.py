from pathlib import Path

import json

import joblib
import pandas as pd
from sklearn.ensemble import IsolationForest


ROOT = Path(__file__).resolve().parent
CLEAN_PATH = ROOT / "calcofi_relevant.csv"
BASELINE_PATH = ROOT / "baselines.json"
MODEL_PATH = ROOT / "isolation_forest.pkl"
REPLAY_PATH = ROOT / "mooring_replay.csv"
NORMAL_CORE_SIGMA = 0.65
MODEL_CONTAMINATION = 0.25

TRAIN_BOUNDS = {
    "lat_min": 27.0,
    "lat_max": 38.0,
    "lon_min": -125.0,
    "lon_max": -115.0,
    "oxygen_min": 0.0,
    "oxygen_max": 15.0,
}


def load_baselines():
    rows = json.loads(BASELINE_PATH.read_text())
    return {int(row["month"]): row for row in rows}


def zscore(value: float, mean: float, std: float) -> float:
    if std in (None, 0):
        return 0.0
    return (value - mean) / std


def load_training_frame():
    df = pd.read_csv(CLEAN_PATH, parse_dates=["timestamp"])
    df = df[df["station_lat"].between(TRAIN_BOUNDS["lat_min"], TRAIN_BOUNDS["lat_max"])].copy()
    df = df[df["station_lon"].between(TRAIN_BOUNDS["lon_min"], TRAIN_BOUNDS["lon_max"])].copy()
    df = df[df["dissolved_oxygen"].between(TRAIN_BOUNDS["oxygen_min"], TRAIN_BOUNDS["oxygen_max"])].copy()
    df = df.dropna(subset=["timestamp", "temp_c", "salinity", "dissolved_oxygen"])
    return df


def build_feature_frame(df: pd.DataFrame, baselines: dict[int, dict]) -> pd.DataFrame:
    working = df.copy()
    working["month"] = working["timestamp"].dt.month
    working["temp_z"] = working.apply(
        lambda row: zscore(
            row["temp_c"],
            baselines[row["month"]]["temp_mean"],
            baselines[row["month"]]["temp_std"],
        ),
        axis=1,
    )
    working["sal_z"] = working.apply(
        lambda row: zscore(
            row["salinity"],
            baselines[row["month"]]["sal_mean"],
            baselines[row["month"]]["sal_std"],
        ),
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
    working = working[["temp_z", "sal_z", "oxygen_z"]].replace([float("inf"), float("-inf")], pd.NA).dropna()
    return working


def trim_training_features(features: pd.DataFrame) -> pd.DataFrame:
    # Train on a tight historically normal core so the model reacts when the
    # replay moves into the warmer / lower-salinity edge of the distribution.
    trimmed = features[
        features["temp_z"].abs().le(NORMAL_CORE_SIGMA)
        & features["sal_z"].abs().le(NORMAL_CORE_SIGMA)
        & features["oxygen_z"].abs().le(NORMAL_CORE_SIGMA)
    ].copy()
    if trimmed.empty:
        raise ValueError("Training trim removed all rows.")
    return trimmed


def train_model(features: pd.DataFrame) -> IsolationForest:
    model = IsolationForest(
        n_estimators=300,
        contamination=MODEL_CONTAMINATION,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(features[["temp_z", "sal_z", "oxygen_z"]])
    return model


def evaluate_replay(model: IsolationForest, baselines: dict[int, dict]):
    if not REPLAY_PATH.exists():
        return None

    replay = pd.read_csv(REPLAY_PATH, parse_dates=["timestamp"])
    replay["month"] = replay["timestamp"].dt.month
    replay["temp_z"] = replay.apply(
        lambda row: zscore(
            row["temp_c"],
            baselines[row["month"]]["temp_mean"],
            baselines[row["month"]]["temp_std"],
        ),
        axis=1,
    )
    replay["sal_z"] = replay.apply(
        lambda row: zscore(
            row["salinity"],
            baselines[row["month"]]["sal_mean"],
            baselines[row["month"]]["sal_std"],
        ),
        axis=1,
    )
    replay["oxygen_z"] = replay.apply(
        lambda row: zscore(
            row["dissolved_oxygen"],
            baselines[row["month"]]["oxygen_mean"],
            baselines[row["month"]]["oxygen_std"],
        ),
        axis=1,
    )
    scores = model.decision_function(replay[["temp_z", "sal_z", "oxygen_z"]])
    replay["anomaly_score"] = scores
    replay["is_anomaly"] = replay["anomaly_score"] < -0.1
    return replay


def main():
    print("Loading cleaned CalCOFI training data...")
    baselines = load_baselines()
    frame = load_training_frame()
    features = build_feature_frame(frame, baselines)
    trimmed = trim_training_features(features)

    print(f"Training rows before trim: {len(features):,}")
    print(f"Training rows after trim:  {len(trimmed):,}")
    print(f"Normal-core sigma bound:   {NORMAL_CORE_SIGMA}")
    print(f"Model contamination:       {MODEL_CONTAMINATION}")

    model = train_model(trimmed)
    joblib.dump(model, MODEL_PATH)
    print(f"Wrote trained model: {MODEL_PATH}")

    replay_eval = evaluate_replay(model, baselines)
    if replay_eval is not None:
        print("\nReplay evaluation:")
        print(
            {
                "rows": int(len(replay_eval)),
                "min_score": round(float(replay_eval["anomaly_score"].min()), 4),
                "max_score": round(float(replay_eval["anomaly_score"].max()), 4),
                "anomaly_rows": int(replay_eval["is_anomaly"].sum()),
            }
        )
        print(
            replay_eval[
                [
                    "timestamp",
                    "temp_c",
                    "salinity",
                    "dissolved_oxygen",
                    "anomaly_score",
                    "is_anomaly",
                ]
            ]
            .head(8)
            .to_string(index=False)
        )


if __name__ == "__main__":
    main()
