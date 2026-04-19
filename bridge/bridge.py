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
import pandas as pd


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
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    return response


def env(name: str, default=None):
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


GEMINI_KEY = env("GEMINI_KEY")
AWS_REGION = env("AWS_REGION", "us-west-2")
DATA_BUCKET = env("S3_DATA_BUCKET", "aegis-ocean-data")
ALERTS_BUCKET = env("S3_ALERTS_BUCKET", "aegis-ocean-alerts")
REPLAY_INTERVAL_SECONDS = float(env("REPLAY_INTERVAL_SECONDS", "2"))
DB_PATH = ROOT / "readings.db"

gemini = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None
s3 = boto3.client("s3", region_name=AWS_REGION)

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
    response = gemini.models.generate_content(model="gemini-2.0-flash", contents=prompt)
    return (response.text or "").strip()


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


@app.route("/alert/latest")
def alert_latest():
    with state_lock:
        return jsonify(dict(latest_alert))


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
