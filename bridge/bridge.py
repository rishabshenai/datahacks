from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv
from google import genai
import json
import os
import time


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

app = Flask(__name__)
CORS(app)


def env(name, default=None):
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


GEMINI_KEY = env("GEMINI_KEY")
AWS_REGION = env("AWS_REGION", "us-west-2")
DATA_BUCKET = env("S3_DATA_BUCKET", "aegis-ocean-data")

gemini = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None
s3 = boto3.client("s3", region_name=AWS_REGION)

DATASET_KEYS = {
    "baselines": "baselines.json",
    "splats": "splats.json",
}

FALLBACK_BASELINES = [
    {"month": 1, "temp_mean": 13.1, "temp_std": 1.5, "sal_mean": 33.4, "n_samples": 1200},
    {"month": 4, "temp_mean": 14.2, "temp_std": 1.8, "sal_mean": 33.5, "n_samples": 1310},
    {"month": 7, "temp_mean": 17.5, "temp_std": 2.1, "sal_mean": 33.7, "n_samples": 1460},
    {"month": 10, "temp_mean": 16.5, "temp_std": 1.8, "sal_mean": 33.6, "n_samples": 1290},
]

FALLBACK_SPLATS = [
    {"x": -0.42, "y": 0.13, "z": -0.05, "temp": 16.8, "sal": 33.5, "anomaly": 0.12, "scale": 0.008},
    {"x": -0.38, "y": 0.11, "z": -0.24, "temp": 14.3, "sal": 33.8, "anomaly": -0.08, "scale": 0.007},
    {"x": -0.35, "y": 0.09, "z": -0.46, "temp": 12.9, "sal": 34.0, "anomaly": -0.16, "scale": 0.006},
    {"x": -0.31, "y": 0.16, "z": -0.12, "temp": 18.1, "sal": 33.4, "anomaly": 0.22, "scale": 0.009},
]

dataset_cache = {}
state = {
    "last_error": "",
    "last_loaded_at": 0.0,
}


def fallback_dataset(name):
    if name == "baselines":
        return FALLBACK_BASELINES
    if name == "splats":
        return FALLBACK_SPLATS
    return []


def load_dataset(name, force_refresh=False):
    if name not in DATASET_KEYS:
        raise KeyError(f"Unknown dataset: {name}")

    if not force_refresh and name in dataset_cache:
        return dataset_cache[name], "cache"

    key = DATASET_KEYS[name]
    try:
        response = s3.get_object(Bucket=DATA_BUCKET, Key=key)
        payload = response["Body"].read().decode("utf-8")
        data = json.loads(payload)
        dataset_cache[name] = data
        state["last_loaded_at"] = time.time()
        return data, "s3"
    except (BotoCoreError, ClientError, json.JSONDecodeError) as exc:
        state["last_error"] = f"S3 dataset load error for {key}: {exc}"
        print(state["last_error"])
        data = fallback_dataset(name)
        dataset_cache[name] = data
        return data, "fallback"


def summarize_records(name, records):
    if name == "baselines":
        temps = [item["temp_mean"] for item in records if "temp_mean" in item]
        salinities = [item["sal_mean"] for item in records if "sal_mean" in item]
        return {
            "dataset": name,
            "records": len(records),
            "temp_mean_min": min(temps) if temps else None,
            "temp_mean_max": max(temps) if temps else None,
            "sal_mean_min": min(salinities) if salinities else None,
            "sal_mean_max": max(salinities) if salinities else None,
        }

    if name == "splats":
        temps = [item["temp"] for item in records if "temp" in item]
        anomalies = [item["anomaly"] for item in records if "anomaly" in item]
        return {
            "dataset": name,
            "records": len(records),
            "temp_min": min(temps) if temps else None,
            "temp_max": max(temps) if temps else None,
            "anomaly_min": min(anomalies) if anomalies else None,
            "anomaly_max": max(anomalies) if anomalies else None,
        }

    return {"dataset": name, "records": len(records)}


def fallback_insight(dataset_name, summary, question):
    return (
        f"This {dataset_name} slice shows {summary['records']} records. "
        f"For marine biologists, the next step is to compare these values across depth, season, and location to separate long-term shifts from local variability. "
        f"Question focus: {question}"
    )


def generate_insight(dataset_name, records, question):
    summary = summarize_records(dataset_name, records)
    sample = records[: min(len(records), 8)]

    if not gemini:
        return fallback_insight(dataset_name, summary, question)

    prompt = f"""You are helping marine biologists interpret ocean data.
Dataset: {dataset_name}
Question: {question}
Summary statistics: {json.dumps(summary)}
Sample records: {json.dumps(sample)}

Write a concise insight in 3 short paragraphs:
1. What patterns stand out.
2. Why they might matter scientifically.
3. What follow-up analysis or field validation a marine biologist should do next.

Avoid hype. Be careful about uncertainty. Do not invent missing evidence."""
    response = gemini.models.generate_content(model="gemini-2.0-flash", contents=prompt)
    return response.text or fallback_insight(dataset_name, summary, question)


@app.route("/health")
def health():
    return jsonify(
        {
            "ok": True,
            "gemini_configured": bool(GEMINI_KEY),
            "aws_region": AWS_REGION,
            "data_bucket": DATA_BUCKET,
            "datasets": list(DATASET_KEYS.keys()),
            "cached_datasets": sorted(dataset_cache.keys()),
            "last_error": state["last_error"],
        }
    )


@app.route("/datasets")
def datasets():
    payload = []
    for name in DATASET_KEYS:
        records, source = load_dataset(name)
        payload.append(
            {
                "name": name,
                "key": DATASET_KEYS[name],
                "source": source,
                "summary": summarize_records(name, records),
            }
        )
    return jsonify(payload)


@app.route("/dataset/<name>")
def dataset_detail(name):
    if name not in DATASET_KEYS:
        return jsonify({"error": f"Unknown dataset '{name}'"}), 404

    records, source = load_dataset(name, force_refresh=request.args.get("refresh") == "1")
    limit = request.args.get("limit", default=25, type=int) or 25
    limit = max(1, min(limit, 200))
    return jsonify(
        {
            "name": name,
            "key": DATASET_KEYS[name],
            "source": source,
            "summary": summarize_records(name, records),
            "records": records[:limit],
        }
    )


@app.route("/insight", methods=["POST"])
def insight():
    payload = request.get_json(silent=True) or {}
    dataset_name = payload.get("dataset", "baselines")
    question = (payload.get("question") or "").strip()

    if dataset_name not in DATASET_KEYS:
        return jsonify({"error": f"Unknown dataset '{dataset_name}'"}), 404

    if not question:
        return jsonify({"error": "question is required"}), 400

    records, source = load_dataset(dataset_name)
    insight_text = generate_insight(dataset_name, records, question)
    return jsonify(
        {
            "dataset": dataset_name,
            "source": source,
            "summary": summarize_records(dataset_name, records),
            "insight": insight_text,
        }
    )


if __name__ == "__main__":
    app.run(port=5000, debug=False)
