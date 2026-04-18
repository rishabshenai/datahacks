#!/usr/bin/env python3
"""
demo_recording.py — Aegis Ocean Hardware-Free Demo Bridge
Run: python bridge/demo_recording.py

Replays a scripted "High Intensity" sensor sequence that cycles through:
  1. Warm-up       (0–15 s)  — stable baseline ~17 °C
  2. Cold plunge   (15–30 s) — 10 °C temperature drop (cold upwelling event)
  3. Recovery      (30–45 s) — gradual return to baseline
  4. Turb. spike   (45–50 s) — 5-second burst at 1.8 m/s²
  5. Cooldown      (50–60 s) — return to calm; cycle repeats

Exposes the same /live and /x-feed endpoints as bridge.py so the frontend
does not need any code changes.

No Arduino required. Gemini insights will fire if GEMINI_KEY is set.
"""

from flask import Flask, jsonify
from flask_cors import CORS
import threading
import time
import math
import random
import os

from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

# ── OPTIONAL GEMINI (insight loop only) ──────────────────────────────────────
_gemini = None
try:
    import google.generativeai as genai
    key = os.getenv("GEMINI_KEY")
    if key:
        genai.configure(api_key=key)
        _gemini = genai.GenerativeModel("gemini-1.5-flash")
        print("✓ Gemini key found — insights will generate every 30 s")
    else:
        print("⚠ No GEMINI_KEY — insights will show fallback text")
except ImportError:
    print("⚠ google-generativeai not installed — insights disabled")

# ── STATE ────────────────────────────────────────────────────────────────────
latest: dict = {
    "temp":               17.0,
    "distance_mm":       100.0,
    "turbulence":          0.0,
    "is_anomaly":        False,
    "turb_spike":        False,
    "simulated":          True,
    "scientific_insight": "Awaiting data stabilization...",
    "gemini_summary":       "",
    "audio_url":            "",
}
_lock = threading.Lock()
_readings_buffer: list = []


# ── SCRIPTED SEQUENCE ────────────────────────────────────────────────────────
# Each phase is (duration_seconds, temp_target, turb_target, dist_target)
PHASES = [
    # Phase 1: Warm-up — stable baseline
    (15, 17.0, 0.10, 100),
    # Phase 2: Cold plunge — 10 °C temperature drop (upwelling simulation)
    (15,  7.0, 0.25, 115),
    # Phase 3: Recovery — gradual return
    (15, 17.0, 0.15, 105),
    # Phase 4: Turbulence spike — 5 seconds of extreme churn
    ( 5, 16.0, 1.80,  90),
    # Phase 5: Cooldown — return to calm
    (10, 17.0, 0.08, 100),
]

CYCLE_LENGTH = sum(p[0] for p in PHASES)  # 60 s total


def get_phase_targets(elapsed: float):
    """Return (temp, turb, dist) interpolated for the current cycle position."""
    t = elapsed % CYCLE_LENGTH
    acc = 0
    prev_temp, prev_turb, prev_dist = PHASES[-1][1], PHASES[-1][2], PHASES[-1][3]

    for dur, temp, turb, dist in PHASES:
        if t < acc + dur:
            # fractional progress within this phase
            frac = (t - acc) / dur
            # smooth ease-in-out via cosine interpolation
            s = 0.5 - 0.5 * math.cos(frac * math.pi)
            return (
                prev_temp + (temp - prev_temp) * s,
                prev_turb + (turb - prev_turb) * s,
                prev_dist + (dist - prev_dist) * s,
            )
        acc += dur
        prev_temp, prev_turb, prev_dist = temp, turb, dist

    return (17.0, 0.1, 100)


# ── PLAYBACK THREAD ──────────────────────────────────────────────────────────
def playback_loop():
    global latest
    start = time.time()
    _last_turb = 0.0
    print("▶ Demo playback started — 60 s cycle")
    print("  0 s  Warm-up (17 °C baseline)")
    print(" 15 s  Cold plunge (→ 7 °C)")
    print(" 30 s  Recovery")
    print(" 45 s  Turbulence spike (1.8 m/s²)")
    print(" 50 s  Cooldown → cycle repeats")
    print()

    while True:
        elapsed = time.time() - start
        temp_t, turb_t, dist_t = get_phase_targets(elapsed)

        # Add realism: small Gaussian noise on top of scripted targets
        temp = round(temp_t + random.gauss(0, 0.3), 1)
        dist = round(dist_t + random.gauss(0, 3.0), 1)
        turb = round(max(0, turb_t + random.gauss(0, 0.02)), 3)

        turb_spike = (turb - _last_turb) > 0.2
        _last_turb = turb

        # Simple anomaly check (same thresholds as bridge.py)
        is_anomaly = abs(temp - 14.2) > 3.6 or turb > 1.0

        # Phase label for console
        cycle_t = elapsed % CYCLE_LENGTH
        if cycle_t < 15:
            phase = "WARM-UP"
        elif cycle_t < 30:
            phase = "COLD PLUNGE ❄️"
        elif cycle_t < 45:
            phase = "RECOVERY"
        elif cycle_t < 50:
            phase = "TURB SPIKE 🔴"
        else:
            phase = "COOLDOWN"

        status = "ANOMALY ⚠" if is_anomaly else "nominal"
        print(f"  [{phase:>14}]  temp={temp:5.1f}°C  turb={turb:.3f} m/s²  dist={dist:5.1f} mm  {status}")

        with _lock:
            _readings_buffer.append({"temp": temp, "dist_mm": dist, "turbulence": turb})
            if len(_readings_buffer) > 10:
                _readings_buffer.pop(0)

            latest.update({
                "temp":        temp,
                "distance_mm": dist,
                "turbulence":  turb,
                "is_anomaly":  is_anomaly,
                "turb_spike":  turb_spike,
                "simulated":   True,
            })

        time.sleep(1)


# ── INSIGHT THREAD ───────────────────────────────────────────────────────────
def insight_loop():
    while True:
        time.sleep(30)
        with _lock:
            buf = list(_readings_buffer)
        if not buf:
            continue

        if _gemini:
            prompt = (
                f"Analyze these consecutive ocean sensor readings "
                f"(Temp °C, Distance mm, Turbulence m/s²): {buf}\n"
                f"Provide a single, one-sentence highly professional "
                f"oceanographic insight about the current state. "
                f"No jargon, just the insight."
            )
            try:
                res = _gemini.generate_content(prompt).text.strip()
                with _lock:
                    latest["scientific_insight"] = res
                print(f"  [INSIGHT] {res[:90]}...")
            except Exception as e:
                print(f"  Gemini insight error: {e}")
                with _lock:
                    latest["scientific_insight"] = "Awaiting data stabilization..."
        else:
            with _lock:
                latest["scientific_insight"] = "Awaiting data stabilization..."


threading.Thread(target=playback_loop, daemon=True).start()
threading.Thread(target=insight_loop,  daemon=True).start()


# ── ROUTES ───────────────────────────────────────────────────────────────────
@app.route("/live")
def live():
    with _lock:
        return jsonify(dict(latest))


@app.route("/x-feed")
def x_feed():
    # Static demo posts — no API key needed
    return jsonify([
        {"text": "🚨 Unusual water temps reported off La Jolla Cove this morning. Surfers say it felt noticeably colder.", "created_at": "2026-04-18T10:32:00Z"},
        {"text": "Red tide advisory issued for San Diego coastline. Avoid swimming near Point Loma.", "created_at": "2026-04-18T09:15:00Z"},
        {"text": "Kelp forest survey update: significant thinning observed in Torrey Pines underwater reserve.", "created_at": "2026-04-18T08:45:00Z"},
        {"text": "Fish kill reported near Imperial Beach. County officials investigating potential runoff contamination.", "created_at": "2026-04-17T16:20:00Z"},
        {"text": "Scripps researchers: California Current showing unusual thermal stratification patterns this week.", "created_at": "2026-04-17T14:00:00Z"},
    ])


if __name__ == "__main__":
    print()
    print("╔══════════════════════════════════════════════════╗")
    print("║     AEGIS OCEAN — Demo Recording Bridge         ║")
    print("║     http://localhost:5000/live                   ║")
    print("║                                                  ║")
    print("║  No hardware required. 60-second cycle.          ║")
    print("║  Open frontend at http://localhost:8080           ║")
    print("╚══════════════════════════════════════════════════╝")
    print()
    app.run(port=5000, debug=False)
