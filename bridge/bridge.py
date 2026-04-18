#!/usr/bin/env python3
"""
bridge.py — Aegis Ocean Flask Bridge
Run: python bridge/bridge.py

Requires: pip install flask flask-cors pyserial boto3 tweepy google-generativeai requests python-dotenv

Architecture:
  Arduino (Serial JSON) → serial_loop thread → latest{} dict
                                                     ↑
  GET /live  ─────────────────────────────────────── ┘  (Three.js polls every 3 s)
  GET /x-feed ─── Tweepy recent-search ──────────────── (sidebar social feed)
  Anomaly event → Gemini summary → ElevenLabs TTS → S3 MP3 URL
"""

from flask import Flask, jsonify
from flask_cors import CORS
import serial
import json
import threading
import time
import boto3
import requests
import tweepy
import google.generativeai as genai
from dotenv import load_dotenv
import os

load_dotenv()

app = Flask(__name__)
CORS(app)

# ── CONFIG ───────────────────────────────────────────────────────────────────
genai.configure(api_key=os.getenv("GEMINI_KEY"))
gemini    = genai.GenerativeModel("gemini-1.5-flash")
x_client  = tweepy.Client(bearer_token=os.getenv("BEARER_TOKEN"))
s3        = boto3.client("s3", region_name=os.getenv("AWS_REGION", "us-west-2"))
VOICE_ID  = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Rachel
ELABS_KEY = os.getenv("ELEVENLABS_KEY")
BUCKET    = os.getenv("S3_ALERTS_BUCKET",  "aegis-ocean-alerts")
LIVE_BUCK = os.getenv("S3_LIVE_BUCKET",    "aegis-ocean-live")

# ── STATE ────────────────────────────────────────────────────────────────────
# NOTE: no 'ph' key — pH sensor is not available in the Modulino kit.
latest: dict = {
    "temp":           17.0,
    "distance_mm":   100.0,
    "turbulence":      0.0,
    "is_anomaly":    False,
    "gemini_summary":   "",
    "audio_url":        "",
}
_lock = threading.Lock()

# ── MONTHLY BASELINES (CalCOFI 75-yr surface records) ────────────────────────
BASELINES: dict[int, dict] = {
    1:  {"temp_mean": 13.1, "temp_std": 1.5, "dist_mean": 100, "dist_std": 10},
    2:  {"temp_mean": 13.0, "temp_std": 1.6, "dist_mean": 100, "dist_std": 10},
    3:  {"temp_mean": 13.3, "temp_std": 1.7, "dist_mean": 100, "dist_std": 10},
    4:  {"temp_mean": 14.2, "temp_std": 1.8, "dist_mean": 100, "dist_std": 10},
    5:  {"temp_mean": 15.0, "temp_std": 1.9, "dist_mean": 100, "dist_std": 10},
    6:  {"temp_mean": 16.1, "temp_std": 2.0, "dist_mean": 100, "dist_std": 10},
    7:  {"temp_mean": 17.5, "temp_std": 2.1, "dist_mean": 100, "dist_std": 10},
    8:  {"temp_mean": 18.2, "temp_std": 2.0, "dist_mean": 100, "dist_std": 10},
    9:  {"temp_mean": 17.8, "temp_std": 1.9, "dist_mean": 100, "dist_std": 10},
    10: {"temp_mean": 16.5, "temp_std": 1.8, "dist_mean": 100, "dist_std": 10},
    11: {"temp_mean": 14.8, "temp_std": 1.7, "dist_mean": 100, "dist_std": 10},
    12: {"temp_mean": 13.5, "temp_std": 1.6, "dist_mean": 100, "dist_std": 10},
}


def get_baseline() -> dict:
    return BASELINES.get(time.localtime().tm_mon, BASELINES[4])


def check_anomaly(temp: float, distance_mm: float, turbulence: float):
    b      = get_baseline()
    temp_z = abs(temp         - b["temp_mean"]) / b["temp_std"]
    dist_z = abs(distance_mm  - b["dist_mean"]) / b["dist_std"]
    turb_z = turbulence / 0.5   # 0.5 m/s² baseline threshold
    is_anom = temp_z > 2.0 or dist_z > 2.0 or turb_z > 2.0
    return is_anom, temp_z, dist_z, turb_z


# FIX §6.1: correct signature — no ph args (pH sensor removed)
def generate_gemini_alert(
    temp: float, dist_mm: float, turbulence: float,
    temp_z: float, dist_z: float, turb_z: float,
) -> str:
    b = get_baseline()
    signals = [("temperature", temp_z), ("water level", dist_z), ("wave turbulence", turb_z)]
    primary = max(signals, key=lambda x: x[1])[0]
    prompt = f"""Ocean health anomaly detected by a Sentinel buoy in the California Current.

Current readings:
- Surface temperature: {temp:.1f}°C  (monthly mean {b["temp_mean"]:.1f}°C, {temp_z:.1f} std devs above normal)
- Water level change:  {dist_mm:.0f} mm from sensor  ({dist_z:.1f} std devs)
- Wave turbulence:     {turbulence:.2f} m/s² above baseline  ({turb_z:.1f} std devs)
- Primary trigger:     {primary}

Write a 2-sentence alert for fishermen and harbor masters.
Sentence 1: what is happening.
Sentence 2: who should act and how.
Under 50 words. Plain language. No jargon."""
    return gemini.generate_content(prompt).text.strip()


def generate_voice(text: str) -> str:
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}",
        headers={"xi-api-key": ELABS_KEY, "Content-Type": "application/json"},
        json={
            "text": text,
            "model_id": "eleven_monolingual_v1",
            "voice_settings": {"stability": 0.7, "similarity_boost": 0.8},
        },
        timeout=30,
    )
    r.raise_for_status()
    key = f"alert_{int(time.time())}.mp3"
    s3.put_object(
        Bucket=BUCKET, Key=key, Body=r.content,
        ContentType="audio/mpeg", ACL="public-read",
    )
    return f"https://{BUCKET}.s3.amazonaws.com/{key}"


# ── SERIAL THREAD ────────────────────────────────────────────────────────────
def serial_loop():
    global latest
    port = os.getenv("ARDUINO_PORT", "/dev/ttyACM0")
    try:
        ser = serial.Serial(port, 9600, timeout=2)
        print(f"✓ Arduino connected on {port}")
        while True:
            line = ser.readline().decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                # FIX §6.1: extract Modulino fields — no ph
                temp       = float(d["temp"])
                dist_mm    = float(d["distance_mm"])
                turbulence = float(d["turbulence"])

                is_anom, temp_z, dist_z, turb_z = check_anomaly(temp, dist_mm, turbulence)

                with _lock:
                    latest.update({
                        "temp":        temp,
                        "distance_mm": dist_mm,
                        "turbulence":  turbulence,
                        "is_anomaly":  is_anom,
                    })

                # FIX §6.1: S3 payload uses only available Modulino fields
                try:
                    s3.put_object(
                        Bucket=LIVE_BUCK,
                        Key=f"readings/{int(time.time())}.json",
                        Body=json.dumps({
                            "temp":        temp,
                            "distance_mm": dist_mm,
                            "turbulence":  turbulence,
                            "timestamp":   time.time(),
                        }),
                    )
                except Exception as s3_err:
                    print(f"  S3 write skipped: {s3_err}")

                if is_anom:
                    # FIX §6.1: correct argument order — match function signature
                    summary = generate_gemini_alert(
                        temp, dist_mm, turbulence, temp_z, dist_z, turb_z
                    )
                    print(f"ALERT: {summary[:100]}…")
                    try:
                        audio_url = generate_voice(summary)
                    except Exception as tts_err:
                        print(f"  TTS skipped: {tts_err}")
                        audio_url = ""
                    with _lock:
                        latest["gemini_summary"] = summary
                        latest["audio_url"]       = audio_url

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                print(f"Parse error: {e} | line: {line!r}")

    except Exception as e:
        print(f"Serial error: {e} — running simulation mode")
        _simulate()


def _simulate():
    """Fallback simulation when Arduino is not connected."""
    import random
    print("▶ Simulation mode active (no serial port)")
    while True:
        temp  = round(14.2 + random.gauss(0, 2.5), 1)
        dist  = round(100  + random.gauss(0, 20),  1)
        turb  = round(abs(random.gauss(0, 0.4)),   3)
        is_a, tz, dz, tbz = check_anomaly(temp, dist, turb)

        with _lock:
            latest.update({
                "temp":        temp,
                "distance_mm": dist,
                "turbulence":  turb,
                "is_anomaly":  is_a,
            })

        if is_a:
            try:
                summary = generate_gemini_alert(temp, dist, turb, tz, dz, tbz)
                print(f"SIM ALERT: {summary[:80]}…")
                with _lock:
                    latest["gemini_summary"] = summary
            except Exception as e:
                print(f"  Gemini skipped (no key?): {e}")

        time.sleep(3)


threading.Thread(target=serial_loop, daemon=True).start()


# ── ROUTES ───────────────────────────────────────────────────────────────────
@app.route("/live")
def live():
    with _lock:
        return jsonify(dict(latest))


@app.route("/x-feed")
def x_feed():
    query = (
        '("algae bloom" OR "fish kill" OR "red tide" OR "HAB" OR "dead kelp")'
        " (San Diego OR \"La Jolla\" OR \"California coast\") -is:retweet lang:en"
    )
    try:
        tweets = x_client.search_recent_tweets(
            query=query, max_results=10, tweet_fields=["created_at"]
        )
        posts = [
            {"text": t.text, "created_at": str(t.created_at)}
            for t in (tweets.data or [])
        ]
    except Exception as e:
        posts = [{"text": f"Social feed unavailable: {e}", "created_at": ""}]
    return jsonify(posts)


if __name__ == "__main__":
    print("Starting Aegis Ocean bridge on http://localhost:5000")
    app.run(port=5000, debug=False)
