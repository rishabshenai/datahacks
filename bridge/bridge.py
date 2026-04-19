from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv
from google import genai
import io
import json
import os
import sqlite3
import threading
import time

import joblib
import numpy as np
import pandas as pd
from fpdf import FPDF


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = ROOT / "frontend"
load_dotenv(ROOT / ".env")

app = Flask(__name__)
CORS(
    app,
    resources={r"/*": {"origins": ["http://127.0.0.1:8000", "http://localhost:8000"]}},
    supports_credentials=False,
)


@app.after_request
def add_cors_headers(response):
    origin = request.headers.get("Origin")
    allowed = {"http://127.0.0.1:8000", "http://localhost:8000"}
    if origin in allowed:
        response.headers["Access-Control-Allow-Origin"] = origin
    else:
        response.headers["Access-Control-Allow-Origin"] = "http://127.0.0.1:8000"
    response.headers["Vary"] = "Origin"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


def env(name: str, default=None):
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


GEMINI_KEY = env("GEMINI_KEY")
ELEVENLABS_KEY = env("ELEVENLABS_KEY")
ELEVENLABS_VOICE_ID = env("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
AWS_REGION = env("AWS_REGION", "us-west-2")
DATA_BUCKET = env("S3_DATA_BUCKET", "aegis-ocean-data")
ALERTS_BUCKET = env("S3_ALERTS_BUCKET", "aegis-ocean-alerts")
REPLAY_INTERVAL_SECONDS = float(env("REPLAY_INTERVAL_SECONDS", "2"))
DB_PATH = ROOT / "readings.db"

gemini = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None
s3 = boto3.client("s3", region_name=AWS_REGION)

_last_spoken_narrative: str = ""

S3_KEYS = {
    "baselines": "baselines.json",
    "mooring_replay": "mooring_replay.csv",
    "model": "models/isolation_forest.pkl",
    "zone_baselines": "zone_baselines.json",
    "zone_replays": "zone_replays.json",
    "zone_models": "models/zone_models.pkl",
}

LOCAL_FALLBACKS = {
    "baselines": ROOT / "data" / "baselines.json",
    "mooring_replay": ROOT / "data" / "mooring_replay.csv",
    "model": ROOT / "data" / "isolation_forest.pkl",
    "zone_baselines": ROOT / "data" / "zone_baselines.json",
    "zone_replays": ROOT / "data" / "zone_replays.json",
    "zone_models": ROOT / "data" / "zone_models.pkl",
}

state_lock = threading.Lock()
latest_live = {
    "timestamp": None,
    "temp_c": None,
    "salinity": None,
    "dissolved_oxygen": None,
    "station_lat": None,
    "station_lon": None,
    "anomaly_score": None,
    "anomaly_label": "NORMAL",
    "is_anomaly": False,
    "z_scores": {"temp": 0.0, "salinity": 0.0, "oxygen": 0.0},
    "source": "mock",
    "zone": None,
    "zone_key": None,
}
latest_alert = {
    "active": False,
    "timestamp": None,
    "location": None,
    "narrative": "",
    "urgency": "LOW",
    "threat": "",
    "zone": None,
    "zone_key": None,
}

AGENCY_MAP = {
    "del-mar": ["Del Mar City Council", "Scripps Coastal Team"],
    "point-loma": ["SD District 2 Office", "SIO Marine Lab"],
    "south-bay": ["Imperial Beach Mayor", "South Bay Water Quality"]
}
status = {
    "last_error": "",
    "baselines_source": "uninitialized",
    "replay_source": "uninitialized",
    "model_source": "uninitialized",
    "zone_baselines_source": "uninitialized",
    "zone_replays_source": "uninitialized",
    "zone_models_source": "uninitialized",
    "replay_rows": 0,
    "replay_running": False,
    "zone_count": 0,
    "zone_mode_active": False,
}

baselines_by_month: dict[int, dict] = {}
replay_df = pd.DataFrame()
model = None
zone_baselines_by_name: dict[str, dict[int, dict]] = {}
zone_replays_by_name: dict[str, pd.DataFrame] = {}
zone_models: dict[str, object] = {}
latest_zones: dict[str, dict] = {}

# Historical Time Machine: CalCOFI monthly aggregates keyed by (zone_key, year, month)
calcofi_monthly_cache: dict[tuple, dict] = {}
calcofi_year_range: tuple[int, int] = (1949, 2026)

# Zone coordinates used to assign CalCOFI rows to the nearest zone
ZONE_COORDS = {
    "del-mar":    (32.96, -117.27),
    "point-loma": (32.67, -117.24),
    "south-bay":  (32.58, -117.17),
}
CALCOFI_ZONE_RADIUS_DEG = 0.35  # ~39 km radius for zone assignment


class MockIsolationForest:
    def decision_function(self, rows):
        scores = []
        for temp_z, sal_z, oxygen_z in rows:
            magnitude = max(abs(temp_z), abs(sal_z), abs(oxygen_z))
            scores.append(0.3 - 0.2 * magnitude)
        return scores


def sqlite_conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    with sqlite_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                zone TEXT,
                timestamp TEXT NOT NULL,
                temp_c REAL,
                salinity REAL,
                dissolved_oxygen REAL,
                station_lat REAL,
                station_lon REAL,
                temp_z REAL,
                sal_z REAL,
                oxygen_z REAL,
                anomaly_score REAL,
                anomaly_label TEXT,
                is_anomaly INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                zone TEXT,
                timestamp TEXT NOT NULL,
                station_lat REAL,
                station_lon REAL,
                urgency TEXT,
                threat TEXT,
                narrative TEXT,
                raw_payload TEXT
            )
            """
        )
        reading_columns = {row[1] for row in conn.execute("PRAGMA table_info(readings)").fetchall()}
        if "zone" not in reading_columns:
            conn.execute("ALTER TABLE readings ADD COLUMN zone TEXT")
        alert_columns = {row[1] for row in conn.execute("PRAGMA table_info(alerts)").fetchall()}
        if "zone" not in alert_columns:
            conn.execute("ALTER TABLE alerts ADD COLUMN zone TEXT")
        conn.commit()


def load_json_from_s3(key: str):
    response = s3.get_object(Bucket=DATA_BUCKET, Key=key)
    return json.loads(response["Body"].read().decode("utf-8"))


def load_csv_from_s3(key: str):
    response = s3.get_object(Bucket=DATA_BUCKET, Key=key)
    return pd.read_csv(io.BytesIO(response["Body"].read()))


def load_joblib_from_s3(key: str):
    response = s3.get_object(Bucket=DATA_BUCKET, Key=key)
    return joblib.load(io.BytesIO(response["Body"].read()))


def fallback_baselines():
    path = LOCAL_FALLBACKS["baselines"]
    if path.exists():
        with open(path) as f:
            return json.load(f), f"local:{path.name}"

    rows = []
    for month in range(1, 13):
        rows.append(
            {
                "month": month,
                "temp_mean": 13.25,
                "temp_std": 3.37,
                "sal_mean": 33.5,
                "sal_std": 0.3,
                "oxygen_mean": 6.2,
                "oxygen_std": 0.7,
            }
        )
    return rows, "mock"


def fallback_replay():
    path = LOCAL_FALLBACKS["mooring_replay"]
    if path.exists():
        return pd.read_csv(path), f"local:{path.name}"

    timestamps = pd.date_range("2024-04-01 09:00:00", periods=60, freq="2min")
    rows = []
    for idx, ts in enumerate(timestamps):
        if idx < 20:
            temp = 15.8 + idx * 0.01
            sal = 33.45
            oxygen = 6.4
        elif idx < 35:
            temp = 17.0 + (idx - 20) * 0.08
            sal = 33.1 - (idx - 20) * 0.01
            oxygen = 5.5 - (idx - 20) * 0.04
        else:
            temp = 16.4
            sal = 33.3
            oxygen = 5.9

        rows.append(
            {
                "timestamp": ts.isoformat(),
                "temp_c": round(temp, 2),
                "salinity": round(sal, 3),
                "dissolved_oxygen": round(oxygen, 3),
                "station_lat": 32.866,
                "station_lon": -117.257,
            }
        )
    return pd.DataFrame(rows), "mock"


def fallback_model():
    path = LOCAL_FALLBACKS["model"]
    if path.exists():
        return joblib.load(path), f"local:{path.name}"
    return MockIsolationForest(), "mock"


def fallback_zone_baselines():
    path = LOCAL_FALLBACKS["zone_baselines"]
    if path.exists():
        with open(path) as f:
            return json.load(f), f"local:{path.name}"
    return {}, "unavailable"


def fallback_zone_replays():
    path = LOCAL_FALLBACKS["zone_replays"]
    if path.exists():
        with open(path) as f:
            return json.load(f), f"local:{path.name}"
    return {}, "unavailable"


def fallback_zone_models():
    path = LOCAL_FALLBACKS["zone_models"]
    if path.exists():
        return joblib.load(path), f"local:{path.name}"
    return {}, "unavailable"


def normalize_baselines(raw):
    if isinstance(raw, dict):
        normalized = []
        for month, values in raw.items():
            row = {"month": int(month)}
            row.update(values)
            normalized.append(row)
        raw = normalized

    by_month = {}
    for row in raw:
        month = int(row["month"])
        by_month[month] = {
            "month": month,
            "temp_mean": float(row.get("temp_mean", 0.0)),
            "temp_std": max(float(row.get("temp_std", 1.0)), 1e-6),
            "sal_mean": float(row.get("sal_mean", 33.5)),
            "sal_std": max(float(row.get("sal_std", 0.3)), 1e-6),
            "oxygen_mean": float(row.get("oxygen_mean", row.get("dissolved_oxygen_mean", 6.2))),
            "oxygen_std": max(float(row.get("oxygen_std", row.get("dissolved_oxygen_std", 0.7))), 1e-6),
            "ph_mean": row.get("ph_mean"),
            "ph_std": row.get("ph_std"),
        }
    return by_month


def normalize_zone_baselines(raw):
    return {zone_name: normalize_baselines(rows) for zone_name, rows in (raw or {}).items()}


def normalize_zone_replays(raw):
    normalized = {}
    for zone_name, rows in (raw or {}).items():
        df = pd.DataFrame(rows)
        if df.empty:
            continue
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df.sort_values("timestamp", inplace=True)
        df.reset_index(drop=True, inplace=True)
        normalized[zone_name] = df
    return normalized


def zone_mode_available():
    return bool(zone_baselines_by_name and zone_replays_by_name and zone_models)


def load_resources():
    global baselines_by_month, replay_df, model, zone_baselines_by_name, zone_replays_by_name, zone_models

    try:
        baselines_raw = load_json_from_s3(S3_KEYS["baselines"])
        baselines_by_month = normalize_baselines(baselines_raw)
        status["baselines_source"] = "s3"
    except Exception as exc:
        baselines_raw, source = fallback_baselines()
        baselines_by_month = normalize_baselines(baselines_raw)
        status["baselines_source"] = source
        status["last_error"] = f"Baselines load failed: {exc}"

    try:
        replay_df = load_csv_from_s3(S3_KEYS["mooring_replay"])
        status["replay_source"] = "s3"
    except Exception as exc:
        replay_df, source = fallback_replay()
        status["replay_source"] = source
        status["last_error"] = f"Replay load failed: {exc}"

    try:
        model = load_joblib_from_s3(S3_KEYS["model"])
        status["model_source"] = "s3"
    except Exception as exc:
        model, source = fallback_model()
        status["model_source"] = source
        status["last_error"] = f"Model load failed: {exc}"

    replay_df["timestamp"] = pd.to_datetime(replay_df["timestamp"])
    replay_df.sort_values("timestamp", inplace=True)
    replay_df.reset_index(drop=True, inplace=True)
    status["replay_rows"] = len(replay_df)

    try:
        zone_baselines_raw = load_json_from_s3(S3_KEYS["zone_baselines"])
        zone_baselines_by_name = normalize_zone_baselines(zone_baselines_raw)
        status["zone_baselines_source"] = "s3"
    except Exception as exc:
        zone_baselines_raw, source = fallback_zone_baselines()
        zone_baselines_by_name = normalize_zone_baselines(zone_baselines_raw)
        status["zone_baselines_source"] = source
        if source == "unavailable":
            status["last_error"] = f"Zone baselines load failed: {exc}"

    try:
        zone_replays_raw = load_json_from_s3(S3_KEYS["zone_replays"])
        zone_replays_by_name = normalize_zone_replays(zone_replays_raw)
        status["zone_replays_source"] = "s3"
    except Exception as exc:
        zone_replays_raw, source = fallback_zone_replays()
        zone_replays_by_name = normalize_zone_replays(zone_replays_raw)
        status["zone_replays_source"] = source
        if source == "unavailable":
            status["last_error"] = f"Zone replays load failed: {exc}"

    try:
        zone_models = load_joblib_from_s3(S3_KEYS["zone_models"])
        status["zone_models_source"] = "s3"
    except Exception as exc:
        zone_models, source = fallback_zone_models()
        status["zone_models_source"] = source
        if source == "unavailable":
            status["last_error"] = f"Zone models load failed: {exc}"

    status["zone_count"] = len(zone_replays_by_name)
    status["zone_mode_active"] = zone_mode_available()

    # Build CalCOFI monthly cache for the Historical Time Machine
    build_calcofi_cache()


def build_calcofi_cache():
    """Pre-aggregate calcofi_relevant.csv into per-zone monthly averages keyed by (zone, year, month)."""
    global calcofi_monthly_cache, calcofi_year_range
    csv_path = ROOT / "data" / "calcofi_relevant.csv"
    if not csv_path.exists():
        print("[TimeMachine] calcofi_relevant.csv not found – historical endpoint will return 404.")
        return

    print("[TimeMachine] Loading CalCOFI CSV and building monthly cache...")
    try:
        df = pd.read_csv(csv_path, parse_dates=["timestamp"])
    except Exception as exc:
        print(f"[TimeMachine] Failed to read CalCOFI CSV: {exc}")
        return

    # Assign each row to the nearest zone (within CALCOFI_ZONE_RADIUS_DEG)
    zone_assignments = []
    lat_arr = df["station_lat"].values
    lon_arr = df["station_lon"].values
    for idx in range(len(df)):
        lat, lon = lat_arr[idx], lon_arr[idx]
        best_zone = None
        best_dist = CALCOFI_ZONE_RADIUS_DEG
        for zone_key, (zlat, zlon) in ZONE_COORDS.items():
            dist = np.sqrt((lat - zlat) ** 2 + (lon - zlon) ** 2)
            if dist < best_dist:
                best_dist = dist
                best_zone = zone_key
        zone_assignments.append(best_zone)

    df["zone_key"] = zone_assignments
    df = df.dropna(subset=["zone_key"])

    if df.empty:
        print("[TimeMachine] No CalCOFI rows matched any zone – cache empty.")
        return

    df["year"] = df["timestamp"].dt.year
    # Use the 'month' column if it already exists, otherwise derive it
    if "month" not in df.columns:
        df["month"] = df["timestamp"].dt.month
    else:
        df["month"] = df["month"].astype(int)

    agg_cols = {"temp_c": ["mean", "std", "count"], "salinity": ["mean", "std"], "dissolved_oxygen": ["mean", "std"]}
    grouped = df.groupby(["zone_key", "year", "month"]).agg(agg_cols)

    cache = {}
    for (zone_key, year, month), row in grouped.iterrows():
        cache[(zone_key, int(year), int(month))] = {
            "temp_mean": float(row[("temp_c", "mean")]) if pd.notna(row[("temp_c", "mean")]) else None,
            "temp_std": float(row[("temp_c", "std")]) if pd.notna(row[("temp_c", "std")]) else 1.0,
            "temp_count": int(row[("temp_c", "count")]),
            "sal_mean": float(row[("salinity", "mean")]) if pd.notna(row[("salinity", "mean")]) else None,
            "sal_std": float(row[("salinity", "std")]) if pd.notna(row[("salinity", "std")]) else 0.3,
            "oxygen_mean": float(row[("dissolved_oxygen", "mean")]) if pd.notna(row[("dissolved_oxygen", "mean")]) else None,
            "oxygen_std": float(row[("dissolved_oxygen", "std")]) if pd.notna(row[("dissolved_oxygen", "std")]) else 0.7,
        }

    calcofi_monthly_cache = cache

    years = sorted(set(y for _, y, _ in cache.keys()))
    if years:
        calcofi_year_range = (years[0], years[-1])

    print(f"[TimeMachine] Cache built: {len(cache)} entries, years {calcofi_year_range[0]}–{calcofi_year_range[1]}")


def zscore(value, mean, std):
    return 0.0 if std <= 0 else (value - mean) / std


def label_from_score(score: float):
    if score < -0.115:
        return "CRITICAL"
    if score < -0.09:
        return "ALERT"
    if score < -0.05:
        return "WATCH"
    return "NORMAL"


def current_baseline_for(timestamp):
    month = pd.Timestamp(timestamp).month
    return baselines_by_month.get(month) or baselines_by_month.get(4) or next(iter(baselines_by_month.values()))


def current_zone_baseline_for(zone_name, timestamp):
    zone_baselines = zone_baselines_by_name.get(zone_name)
    if zone_baselines:
        month = pd.Timestamp(timestamp).month
        return zone_baselines.get(month) or next(iter(zone_baselines.values()))
    return current_baseline_for(timestamp)

def store_reading(row, z_scores, score, label, is_anomaly, zone_name=None):
    with sqlite_conn() as conn:
        conn.execute(
            """
            INSERT INTO readings (
                zone, timestamp, temp_c, salinity, dissolved_oxygen, station_lat, station_lon,
                temp_z, sal_z, oxygen_z, anomaly_score, anomaly_label, is_anomaly
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                zone_name,
                pd.Timestamp(row["timestamp"]).isoformat(),
                float(row["temp_c"]),
                float(row["salinity"]),
                float(row["dissolved_oxygen"]),
                float(row["station_lat"]),
                float(row["station_lon"]),
                float(z_scores["temp"]),
                float(z_scores["salinity"]),
                float(z_scores["oxygen"]),
                float(score),
                label,
                int(is_anomaly),
            ),
        )
        conn.commit()


def parse_alert_fields(text: str):
    urgency = "HIGH"
    threat = "Kelp stress anomaly"
    upper = text.upper()
    for level in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
        if level in upper:
            urgency = level
            break

    threats = [
        "marine heatwave",
        "urchin barren formation",
        "ocean acidification",
        "low oxygen zone",
        "salinity shift",
    ]
    lower = text.lower()
    for candidate in threats:
        if candidate in lower:
            threat = candidate.title()
            break
    return urgency, threat


def generate_alert_narrative(row, baseline, z_scores, zone_name=None):
    zone_fragment = f" in the {zone_name.replace('-', ' ').title()} zone" if zone_name else ""
    if not gemini:
        return (
            "Threat: Marine heatwave risk.\n"
            "Urgency: HIGH.\n"
            f"Action: Review this station{zone_fragment} and consider dispatching kelp monitoring or urchin response teams."
        )

    prompt = f"""You are assisting a marine biologist monitoring kelp forest health off the California coast.
An ocean anomaly was detected{zone_fragment} at latitude {row['station_lat']}, longitude {row['station_lon']}.

Reading:
- temp={row['temp_c']}C ({z_scores['temp']:+.1f} sigma)
- salinity={row['salinity']} ({z_scores['salinity']:+.1f} sigma)
- dissolved oxygen={row['dissolved_oxygen']} ({z_scores['oxygen']:+.1f} sigma)

Monthly baseline:
- temp_mean={baseline['temp_mean']}C
- sal_mean={baseline['sal_mean']}
- oxygen_mean={baseline['oxygen_mean']}

Respond in 3 labeled lines:
Threat: which kelp threat this pattern matches
Urgency: LOW, MEDIUM, HIGH, or CRITICAL
Action: what the biologist should investigate and where to dispatch urchin hunters
"""
    response = gemini.models.generate_content(model="models/gemini-2.5-flash", contents=prompt)
    return (response.text or "").strip()


def speak_alert(narrative: str) -> None:
    global _last_spoken_narrative
    if not ELEVENLABS_KEY or narrative == _last_spoken_narrative:
        return
    _last_spoken_narrative = narrative
    try:
        import urllib.request
        spoken_text = narrative.split("Action:")[0].strip()
        payload = json.dumps({
            "text": spoken_text,
            "model_id": "eleven_monolingual_v1",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }).encode()
        req = urllib.request.Request(
            f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}",
            data=payload,
            headers={
                "xi-api-key": ELEVENLABS_KEY,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            audio_bytes = resp.read()

        import subprocess, shutil
        audio_path = ROOT / "alert.mp3"
        audio_path.write_bytes(audio_bytes)

        for player in ("afplay", "mpg123", "ffplay"):
            if shutil.which(player):
                subprocess.Popen(
                    [player] + ([] if player != "ffplay" else ["-nodisp", "-autoexit"]) + [str(audio_path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                break
    except Exception as exc:
        print(f"[TTS] voice alert failed: {exc}")


def store_alert(row, narrative, urgency, threat, zone_name=None):
    payload = {
        "zone": zone_name,
        "timestamp": pd.Timestamp(row["timestamp"]).isoformat(),
        "station_lat": float(row["station_lat"]),
        "station_lon": float(row["station_lon"]),
        "urgency": urgency,
        "threat": threat,
        "narrative": narrative,
    }

    with sqlite_conn() as conn:
        conn.execute(
            """
            INSERT INTO alerts (
                zone, timestamp, station_lat, station_lon, urgency, threat, narrative, raw_payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                zone_name,
                payload["timestamp"],
                payload["station_lat"],
                payload["station_lon"],
                urgency,
                threat,
                narrative,
                json.dumps(payload),
            ),
        )
        conn.commit()

    try:
        s3.put_object(
            Bucket=ALERTS_BUCKET,
            Key=f"alerts/{int(time.time())}.json",
            Body=json.dumps(payload).encode("utf-8"),
            ContentType="application/json",
        )
    except Exception as exc:
        status["last_error"] = f"Alert S3 write failed: {exc}"


def compute_state(row, baseline, active_model, zone_name=None):
    z_scores = {
        "temp": zscore(float(row["temp_c"]), baseline["temp_mean"], baseline["temp_std"]),
        "salinity": zscore(float(row["salinity"]), baseline["sal_mean"], baseline["sal_std"]),
        "oxygen": zscore(float(row["dissolved_oxygen"]), baseline["oxygen_mean"], baseline["oxygen_std"]),
    }
    features = [[z_scores["temp"], z_scores["salinity"], z_scores["oxygen"]]]
    score = float(active_model.decision_function(features)[0])
    label = label_from_score(score)
    is_anomaly = score < -0.05
    return {
        "zone_key": zone_name,
        "zone": zone_name.replace("-", " ").title() if zone_name else None,
        "timestamp": pd.Timestamp(row["timestamp"]).isoformat(),
        "temp_c": float(row["temp_c"]),
        "salinity": float(row["salinity"]),
        "dissolved_oxygen": float(row["dissolved_oxygen"]),
        "station_lat": float(row["station_lat"]),
        "station_lon": float(row["station_lon"]),
        "anomaly_score": score,
        "anomaly_label": label,
        "is_anomaly": is_anomaly,
        "z_scores": z_scores,
    }


def process_row(row, zone_name=None):
    baseline = current_zone_baseline_for(zone_name, row["timestamp"]) if zone_name else current_baseline_for(row["timestamp"])
    active_model = zone_models.get(zone_name, model) if zone_name else model
    state = compute_state(row, baseline, active_model, zone_name)
    store_reading(row, state["z_scores"], state["anomaly_score"], state["anomaly_label"], state["is_anomaly"], zone_name)

    if state["is_anomaly"]:
        narrative = generate_alert_narrative(row, baseline, state["z_scores"], zone_name)
        urgency, threat = parse_alert_fields(narrative)
        state["alert"] = {
            "active": True,
            "timestamp": state["timestamp"],
            "location": {"lat": state["station_lat"], "lon": state["station_lon"]},
            "narrative": narrative,
            "urgency": urgency,
            "threat": threat,
            "zone": state["zone"],
            "zone_key": state["zone_key"],
        }
        store_alert(row, narrative, urgency, threat, zone_name)
        threading.Thread(target=speak_alert, args=(narrative,), daemon=True).start()
    return state


def update_global_state_from_zone_states(zone_states):
    if not zone_states:
        return
    worst_state = min(zone_states, key=lambda item: item["anomaly_score"])
    with state_lock:
        latest_zones.clear()
        for state in zone_states:
            latest_zones[state["zone_key"]] = {
                **state,
                "source": status["zone_replays_source"],
            }
        latest_live.update({**worst_state, "source": status["zone_replays_source"]})

        anomalous_states = [state for state in zone_states if state["is_anomaly"]]
        if anomalous_states:
            worst_alert = min(anomalous_states, key=lambda item: item["anomaly_score"])
            latest_alert.update(worst_alert["alert"])
        else:
            latest_alert.update(
                {
                    "active": False,
                    "timestamp": worst_state["timestamp"],
                    "location": {"lat": worst_state["station_lat"], "lon": worst_state["station_lon"]},
                    "narrative": "",
                    "urgency": "LOW",
                    "threat": "",
                    "zone": worst_state["zone"],
                    "zone_key": worst_state["zone_key"],
                }
            )


def replay_loop():
    status["replay_running"] = True
    if zone_mode_available():
        zone_names = sorted(zone_replays_by_name)
        step_count = min(len(zone_replays_by_name[name]) for name in zone_names)
        while True:
            for idx in range(step_count):
                zone_states = []
                for zone_name in zone_names:
                    try:
                        row = zone_replays_by_name[zone_name].iloc[idx]
                        zone_states.append(process_row(row, zone_name=zone_name))
                    except Exception as exc:
                        status["last_error"] = f"Zone replay processing error ({zone_name}): {exc}"
                update_global_state_from_zone_states(zone_states)
                time.sleep(REPLAY_INTERVAL_SECONDS)

    while True:
        for _, row in replay_df.iterrows():
            try:
                state = process_row(row)
                with state_lock:
                    latest_live.update({**state, "source": status["replay_source"]})
                    if state["is_anomaly"]:
                        latest_alert.update(state["alert"])
            except Exception as exc:
                status["last_error"] = f"Replay processing error: {exc}"
            time.sleep(REPLAY_INTERVAL_SECONDS)


@app.route("/live")
def live():
    with state_lock:
        return jsonify(dict(latest_live))


@app.route("/history")
def history():
    with sqlite_conn() as conn:
        rows = conn.execute(
            """
            SELECT zone, timestamp, temp_c, salinity, dissolved_oxygen, station_lat, station_lon,
                   temp_z, sal_z, oxygen_z, anomaly_score, anomaly_label, is_anomaly
            FROM readings
            ORDER BY id DESC
            LIMIT 100
            """
        ).fetchall()

    rows = [
        {
            "zone": row[0],
            "timestamp": row[1],
            "temp_c": row[2],
            "salinity": row[3],
            "dissolved_oxygen": row[4],
            "station_lat": row[5],
            "station_lon": row[6],
            "z_scores": {"temp": row[7], "salinity": row[8], "oxygen": row[9]},
            "anomaly_score": row[10],
            "anomaly_label": row[11],
            "is_anomaly": bool(row[12]),
        }
        for row in rows
    ]
    return jsonify(rows)


@app.route("/baseline")
def baseline():
    timestamp = latest_live["timestamp"] or pd.Timestamp.utcnow().isoformat()
    zone_key = latest_live.get("zone_key")
    baseline = current_zone_baseline_for(zone_key, timestamp) if zone_key else current_baseline_for(timestamp)
    return jsonify(baseline)


@app.route("/zones/live")
def zones_live():
    with state_lock:
        return jsonify(dict(latest_zones))


@app.route("/zones/historical")
def zones_historical():
    """Return per-zone state for a given historical year/month using CalCOFI monthly cache."""
    year = request.args.get("year", type=int)
    month = request.args.get("month", type=int)
    if not year or not month or month < 1 or month > 12:
        return jsonify({"error": "year and month (1-12) are required"}), 400

    if not calcofi_monthly_cache:
        return jsonify({"error": "Historical CalCOFI cache not available"}), 503

    result = {}
    for zone_key, (zlat, zlon) in ZONE_COORDS.items():
        entry = calcofi_monthly_cache.get((zone_key, year, month))
        if not entry or entry["temp_mean"] is None:
            # Try adjacent months within the same year
            for delta in [1, -1, 2, -2]:
                alt_month = month + delta
                if 1 <= alt_month <= 12:
                    entry = calcofi_monthly_cache.get((zone_key, year, alt_month))
                    if entry and entry["temp_mean"] is not None:
                        break
            else:
                entry = None

        if not entry or entry["temp_mean"] is None:
            # Provide a null-safe fallback
            result[zone_key] = {
                "zone_key": zone_key,
                "zone": zone_key.replace("-", " ").title(),
                "timestamp": f"{year}-{month:02d}-15T12:00:00",
                "temp_c": None,
                "salinity": None,
                "dissolved_oxygen": None,
                "station_lat": zlat,
                "station_lon": zlon,
                "anomaly_score": 0.0,
                "anomaly_label": "NO DATA",
                "is_anomaly": False,
                "z_scores": {"temp": 0.0, "salinity": 0.0, "oxygen": 0.0},
                "source": "calcofi-historical",
                "historical_month": {"year": year, "month": month},
            }
            continue

        # Compute z-scores against the 75-year baseline for this zone/month
        baseline = current_zone_baseline_for(zone_key, f"{year}-{month:02d}-15")
        temp_val = entry["temp_mean"]
        sal_val = entry["sal_mean"] if entry["sal_mean"] is not None else baseline["sal_mean"]
        oxy_val = entry["oxygen_mean"] if entry["oxygen_mean"] is not None else baseline["oxygen_mean"]

        z_scores = {
            "temp": zscore(temp_val, baseline["temp_mean"], baseline["temp_std"]),
            "salinity": zscore(sal_val, baseline["sal_mean"], baseline["sal_std"]),
            "oxygen": zscore(oxy_val, baseline["oxygen_mean"], baseline["oxygen_std"]),
        }

        active_model = zone_models.get(zone_key, model)
        features = [[z_scores["temp"], z_scores["salinity"], z_scores["oxygen"]]]
        score = float(active_model.decision_function(features)[0]) if active_model else 0.0
        label = label_from_score(score)
        is_anomaly = score < -0.05

        result[zone_key] = {
            "zone_key": zone_key,
            "zone": zone_key.replace("-", " ").title(),
            "timestamp": f"{year}-{month:02d}-15T12:00:00",
            "temp_c": round(temp_val, 2),
            "salinity": round(sal_val, 3),
            "dissolved_oxygen": round(oxy_val, 3) if oxy_val else None,
            "station_lat": zlat,
            "station_lon": zlon,
            "anomaly_score": round(score, 4),
            "anomaly_label": label,
            "is_anomaly": is_anomaly,
            "z_scores": {k: round(v, 3) for k, v in z_scores.items()},
            "source": "calcofi-historical",
            "historical_month": {"year": year, "month": month},
            "calcofi_count": entry["temp_count"],
        }

    return jsonify(result)


@app.route("/zones/historical/range")
def zones_historical_range():
    """Return the min/max year range available in the CalCOFI cache."""
    return jsonify({"minYear": calcofi_year_range[0], "maxYear": calcofi_year_range[1]})


@app.route("/alert/latest")
def alert_latest():
    with state_lock:
        return jsonify(dict(latest_alert))


@app.route("/alert/trigger", methods=["POST", "OPTIONS"])
def alert_trigger():
    if request.method == "OPTIONS":
        return "", 204
    with state_lock:
        zone_states = dict(latest_zones)

    # Pick the most anomalous zone available
    candidates = [s for s in zone_states.values() if s and s.get("temp_c") is not None]
    if not candidates:
        return jsonify({"ok": False, "error": "No zone data available yet"}), 503

    candidates.sort(key=lambda s: float(s.get("anomaly_score", 0)))
    state = candidates[0]

    row = pd.Series({
        "timestamp": state["timestamp"],
        "temp_c": state["temp_c"],
        "salinity": state["salinity"],
        "dissolved_oxygen": state["dissolved_oxygen"],
        "station_lat": state["station_lat"],
        "station_lon": state["station_lon"],
    })
    baseline = zone_baselines_by_name.get(state["zone_key"], {}).get(
        pd.Timestamp(state["timestamp"]).month, {}
    )
    narrative = generate_alert_narrative(row, baseline, state.get("z_scores", {}), state["zone_key"])
    urgency, threat = parse_alert_fields(narrative)

    alert = {
        "active": True,
        "timestamp": state["timestamp"],
        "location": {"lat": state["station_lat"], "lon": state["station_lon"]},
        "narrative": narrative,
        "urgency": urgency,
        "threat": threat,
        "zone": state["zone"],
        "zone_key": state["zone_key"],
    }
    with state_lock:
        latest_alert.update(alert)

    threading.Thread(target=speak_alert, args=(narrative,), daemon=True).start()
    return jsonify({"ok": True, "alert": alert})


@app.route("/alert/dispatch", methods=["POST", "OPTIONS"])
def alert_dispatch():
    if request.method == "OPTIONS":
        return "", 204
    with state_lock:
        zone_states = dict(latest_zones)

    candidates = [s for s in zone_states.values() if s and s.get("temp_c") is not None]
    if not candidates:
        return jsonify({"ok": False, "error": "No zone data available"}), 503

    candidates.sort(key=lambda s: float(s.get("anomaly_score", 0)))
    state = candidates[0]
    zone_key = state["zone_key"]
    
    agencies = AGENCY_MAP.get(zone_key, ["General Environmental Agency"])

    # Generate PDF Snapshot
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=f"Sentinel Hard-Data Report: {state['zone'].upper()}", ln=1, align="C")
    pdf.cell(200, 10, txt=f"Timestamp: {state['timestamp']}", ln=1)
    pdf.cell(200, 10, txt=f"Lat/Lon: {state['station_lat']}, {state['station_lon']}", ln=1)
    pdf.cell(200, 10, txt=f"Temperature: {state['temp_c']} C", ln=1)
    pdf.cell(200, 10, txt=f"Salinity: {state.get('salinity')} PSU", ln=1)
    pdf.cell(200, 10, txt=f"Dissolved Oxygen: {state.get('dissolved_oxygen')} mL/L", ln=1)
    pdf.cell(200, 10, txt=f"Overall Anomaly Score: {state.get('anomaly_score')}", ln=1)
    
    z_scores = state.get('z_scores', {})
    pdf.cell(200, 10, txt=f"Z-Scores - Temp: {z_scores.get('temp')}, Sal: {z_scores.get('salinity')}, DO: {z_scores.get('oxygen')}", ln=1)
    
    pdf_path = f"/tmp/sentinel_report_{zone_key}_{int(time.time())}.pdf"
    try:
        pdf.output(pdf_path)
    except Exception as e:
        print(f"Error generating PDF: {e}")
        pdf_path = None

    summary = "System error: unable to generate summary."
    if gemini:
        prompt = f"""You are an Aegis Ocean AI Sentinel. Summarize these Z-scores and metrics for a non-technical official.
Focus on kelp die-off risk and immediate environmental threats. Keep it urgent but professional.
[LIVE_DATA]: Zone: {state['zone']}, Temp: {state['temp_c']}C, Salinity: {state.get('salinity')}, DO: {state.get('dissolved_oxygen')}.
Z-scores: {z_scores}"""
        try:
            resp = gemini.models.generate_content(model="models/gemini-2.5-flash", contents=prompt)
            summary = resp.text
        except Exception as e:
            print(f"Gemini error: {e}")

    return jsonify({
        "ok": True,
        "summary": summary,
        "zone": state["zone"],
        "zone_key": zone_key,
        "agencies": agencies,
        "pdf_path": pdf_path
    })


@app.route("/health")
def health():
    return jsonify(
        {
            "ok": True,
            "gemini_configured": bool(GEMINI_KEY),
            "aws_region": AWS_REGION,
            "data_bucket": DATA_BUCKET,
            "alerts_bucket": ALERTS_BUCKET,
            "baselines_source": status["baselines_source"],
            "replay_source": status["replay_source"],
            "model_source": status["model_source"],
            "zone_baselines_source": status["zone_baselines_source"],
            "zone_replays_source": status["zone_replays_source"],
            "zone_models_source": status["zone_models_source"],
            "replay_rows": status["replay_rows"],
            "replay_running": status["replay_running"],
            "zone_count": status["zone_count"],
            "zone_mode_active": status["zone_mode_active"],
            "last_error": status["last_error"],
            "db_path": str(DB_PATH),
        }
    )


@app.route("/")
def frontend_index():
    return send_from_directory(FRONTEND_ROOT, "index.html")


@app.route("/<path:filename>")
def frontend_files(filename):
    path = FRONTEND_ROOT / filename
    if path.is_file():
        return send_from_directory(FRONTEND_ROOT, filename)
    return ("Not Found", 404)


init_db()
load_resources()
threading.Thread(target=replay_loop, daemon=True).start()


if __name__ == "__main__":
    app.run(port=5000, debug=False)
