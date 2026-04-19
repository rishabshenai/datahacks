# Aegis Ocean — Technical Team Overview

> **DataHacks 2026 (April 18–19) · Team 404 Fish Now Found · DS3 @ UCSD**

---

## Table of Contents

1. [Project Purpose & Challenge Targets](#1-project-purpose--challenge-targets)
2. [High-Level Architecture](#2-high-level-architecture)
3. [Data Pipeline](#3-data-pipeline)
4. [Component Breakdown](#4-component-breakdown)
   - [Hardware: sentinel_firmware.ino](#41-hardware--sentinel_firmwareino)
   - [Backend: bridge.py](#42-backend--bridgepy)
   - [Demo Server: demo_recording.py](#43-demo-server--demo_recordingpy)
   - [Data Scripts](#44-data-scripts)
   - [Frontend: index.html](#45-frontend--indexhtml)
5. [Algorithms & Models](#5-algorithms--models)
6. [API Reference](#6-api-reference)
7. [Environment & Dependencies](#7-environment--dependencies)
8. [Running the System](#8-running-the-system)

---

## 1. Project Purpose & Challenge Targets

**Aegis Ocean** is a decentralized, real-time ocean health monitoring system that combines physical Arduino sensors with a machine-learning anomaly detection backend and an immersive 3D visualization frontend. The system continuously watches temperature, salinity, and dissolved oxygen across three San Diego coastal zones, flags anomalies against 75 years of CalCOFI oceanographic history, generates AI-powered scientific narratives, and renders the ocean state as a navigable 3D Gaussian point cloud.

### DataHacks Challenges Targeted

| Track | How We Address It |
|---|---|
| **Ocean Health / Marine Ecosystems** | Real-time kelp forest health proxy, urchin pressure scoring, and dissolved oxygen monitoring across three Southern California coastal zones |
| **Anomaly Detection / Environmental ML** | Isolation Forest trained on 75-year CalCOFI climatology; z-score deviation from seasonal baselines; multi-threshold severity classification |
| **Real-World Data Engineering** | Full ETL pipeline from raw CalCOFI CSVs → cleaned baselines → trained models → live API → frontend; 2015 California Current heatwave replay |
| **Hardware + IoT Integration** | Arduino Modulino (Thermo, Distance, IMU) → USB serial JSON → Python bridge; graceful simulation fallback |
| **AI/LLM Integration** | Google Gemini 1.5 Flash for structured anomaly narratives (Threat / Urgency / Action); ElevenLabs TTS voice alerts |
| **3D / Novel Visualization** | Three.js Gaussian splatting (25,000 points), custom GLSL shaders, turbulence-reactive vertex displacement, MapLibre 2D satellite map |

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Arduino Modulino (sentinel_firmware.ino)                │
│  • ModulinoThermo  → temperature (°C)                   │
│  • ModulinoDistance → water level (mm)                  │
│  • ModulinoMovement → 3-axis IMU → turbulence (m/s²)   │
│  Outputs JSON @ 9600 baud over USB Serial every 2s      │
└────────────────────────┬────────────────────────────────┘
                         │ USB Serial (JSON)
                         ▼
┌─────────────────────────────────────────────────────────┐
│  bridge.py  (Flask REST API, port 5000)                  │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │ 1. load_resources()                              │   │
│  │    • CalCOFI baselines (baselines.json)          │   │
│  │    • Mooring replay (mooring_replay.csv)         │   │
│  │    • Global Isolation Forest (isolation_forest)  │   │
│  │    • Zone baselines + zone_models.pkl            │   │
│  │    • Zone replay sequences (zone_replays.json)   │   │
│  └──────────────────────────────────────────────────┘   │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │ 2. replay_loop()  [daemon thread]                │   │
│  │    • Steps through replay_df every 2s             │   │
│  │    • compute_state() → z-scores + IF score       │   │
│  │    • If anomaly → Gemini alert narrative         │   │
│  │    • Stores readings + alerts → SQLite + S3      │   │
│  │    • Updates latest_live, latest_zones           │   │
│  └──────────────────────────────────────────────────┘   │
│                                                          │
│  REST endpoints:                                         │
│  GET /live          GET /zones/live                      │
│  GET /history       GET /alert/latest                    │
│  GET /baseline      GET /health                          │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTP polling @ 1.5s
                       ▼
┌─────────────────────────────────────────────────────────┐
│  index.html  (single-page app, served at :8000)          │
│                                                          │
│  ┌──────────────────────┐  ┌────────────────────────┐   │
│  │  MapLibre-GL 2D Map  │  │  Three.js 3D Scene     │   │
│  │  • CartoDB basemap   │  │  • 25k Gaussian splats │   │
│  │  • Zone markers      │  │  • Custom GLSL shaders │   │
│  │  • Click-to-explore  │  │  • Turbulence displace │   │
│  └──────────────────────┘  └────────────────────────┘   │
│                                                          │
│  UI panels:                                              │
│  • Zone health/pressure cards   • Temperature sparkline  │
│  • AI insight narrative         • Anomaly alert badge    │
│  • Ocean signals (live metrics) • Visualization mode     │
└─────────────────────────────────────────────────────────┘
```

### External Services

| Service | Library | Role |
|---|---|---|
| Google Gemini 1.5 Flash | `google-genai` | Structured anomaly narratives (Threat/Urgency/Action) |
| ElevenLabs TTS | `elevenlabs` | Voice alerts (optional) |
| AWS S3 | `boto3` | Alert + reading archival (optional) |
| X/Twitter API | HTTP (Bearer token) | Coastal event social feed (optional) |
| Scripps ERDDAP | `argopy` | Argo float profiles for real 3D splat data (optional) |

---

## 3. Data Pipeline

All training data originates from the **CalCOFI (California Cooperative Oceanic Fisheries Investigation)** database — 75 years (1949–2021) of oceanographic bottle samples along the California Current.

```
CalCOFI Raw CSVs
(194903-202105_Bottle.csv + Cast.csv, ~100k surface observations)
             │
             ├──► build_baseline.py
             │        • Merges bottle + cast tables on Cst_Cnt
             │        • Filters depth < 200m
             │        • Computes mean/std per month (×12)
             │        └──► data/baselines.json  (12 monthly baselines)
             │
             ├──► build_replay.py
             │        • Geographic filter: 27–38°N, 115–125°W
             │        • Extracts Oct 29–31 2015 heatwave window
             │        • Resamples to 1-hour grid
             │        └──► data/mooring_replay.csv  (65 hourly rows)
             │
             ├──► build_zone_artifacts.py
             │        • Three zones: Del Mar, Point Loma, South Bay
             │        • Per-zone monthly baselines (expanding radius fallback)
             │        • Stress-peak event extraction + Gaussian anomaly injection
             │        • Normalize to 36 × 10-min shared timeline
             │        ├──► data/zone_baselines.json  (3 zones × 12 months)
             │        └──► data/zone_replays.json     (3 zones × 36 timesteps)
             │
             ├──► train_model.py
             │        • Loads baselines.json + calcofi_relevant.csv
             │        • Computes z-scores [temp_z, sal_z, oxygen_z]
             │        • Trims to normal core (|z| ≤ 0.65σ)
             │        • Trains Isolation Forest (300 trees, contamination=0.25)
             │        └──► data/isolation_forest.pkl
             │
             ├──► train_zone_models.py
             │        • Same pipeline per zone (|z| ≤ 0.9σ, 250 trees)
             │        └──► data/zone_models.pkl  (dict of 3 models)
             │
             └──► generate_splats.py
                      • Option A: Argo float profiles via ERDDAP
                      • Option B: Synthetic California Current (default)
                        - 25k points, physically-realistic thermal structure
                        - Marine heatwave blobs + upwelling cold tongues
                      └──► frontend/splats.json  (25k × {x,y,z,temp,sal,anomaly,scale})
```

At runtime, `bridge.py` loads all the above artifacts and replays `mooring_replay.csv` (or zone replays) through the pipeline at 2-second intervals.

---

## 4. Component Breakdown

### 4.1 Hardware — `sentinel_firmware.ino`

**Location:** `hardware/sentinel_firmware/sentinel_firmware.ino`

**Target MCU:** Arduino Uno R4 WiFi (Qwiic connector)

**Sensor Modules (daisy-chained via I²C / Modulino library):**

| Module | Measurement | Output |
|---|---|---|
| ModulinoThermo | Temperature | `temp` (°C) |
| ModulinoDistance | Ultrasonic range | `distance_mm` (mm) |
| ModulinoMovement | 6-axis IMU | `accel_x/y/z` (m/s²) |

**Turbulence Calculation:**
```cpp
float turbulence = sqrt(ax*ax + ay*ay + az*az) - 9.81;
// Removes 1g gravity component; represents net motion energy
```

**Serial Output (every 2 seconds at 9600 baud):**
```json
{
  "temp": 17.23,
  "distance_mm": 104.5,
  "accel_x": 0.123,
  "accel_y": -0.045,
  "accel_z": 9.891,
  "turbulence": 0.234,
  "ts": 123456789
}
```

`bridge.py` reads this JSON stream and feeds it into the anomaly pipeline. If no Arduino is present, the system falls back to replay mode automatically.

---

### 4.2 Backend — `bridge/bridge.py`

**Location:** `bridge/bridge.py`

**Framework:** Flask 3.x with CORS enabled for localhost

**Global State (thread-safe behind `state_lock`):**

```python
latest_live: dict         # current zone state + anomaly metrics
latest_zones: dict        # all three zone states simultaneously
latest_alert: dict        # most recent anomaly event + Gemini narrative
baselines_by_month: dict  # 12 → {temp_mean, temp_std, sal_mean, ...}
zone_baselines_by_name: dict  # zone_id → 12 → baseline
zone_replays_by_name: dict    # zone_id → [36 timesteps]
model: IsolationForest    # global anomaly detector
zone_models: dict         # zone_id → IsolationForest
replay_df: DataFrame      # mooring_replay.csv
```

**Startup sequence:**

1. `load_resources()` — tries S3 first, falls back to local `data/` directory
2. Opens SQLite DB, creates `readings` and `alerts` tables
3. Starts `replay_loop()` as daemon thread

**Key functions:**

| Function | What it does |
|---|---|
| `zscore(v, mean, std)` | Standardizes a value against its seasonal baseline |
| `label_from_score(score)` | Maps IF score → NORMAL / WATCH / ALERT / CRITICAL |
| `compute_state(row, baseline, model)` | Full z-score + IF inference for one timestep |
| `process_row(row, zone_name)` | Runs compute_state, writes SQLite, triggers Gemini if anomalous |
| `generate_alert_narrative(row, baseline, z_scores)` | Prompts Gemini for 3-line structured alert |
| `store_alert(row, narrative, urgency, threat)` | Persists to SQLite + S3 |
| `replay_loop()` | Background thread; iterates replay_df at REPLAY_INTERVAL_SECONDS |

**Anomaly severity thresholds:**

| Isolation Forest Score | Label |
|---|---|
| ≥ −0.05 | NORMAL |
| < −0.05 | WATCH |
| < −0.09 | ALERT |
| < −0.115 | CRITICAL |

**Gemini prompt template:**
```
You are assisting a marine biologist monitoring kelp forest health in the
California Current. An ocean anomaly was detected at [lat/lon] on [date].

Conditions: temp=[X]°C (z=[z]), salinity=[X] PSU (z=[z]),
            oxygen=[X] mL/L (z=[z])

Respond in exactly 3 labeled lines:
Threat: <brief scientific threat classification>
Urgency: LOW | MEDIUM | HIGH | CRITICAL
Action: <recommended immediate response>
```

**SQLite schema:**

```sql
CREATE TABLE readings (
  id INTEGER PRIMARY KEY,
  timestamp TEXT, zone TEXT,
  temp_c REAL, salinity REAL, dissolved_oxygen REAL,
  temp_z REAL, sal_z REAL, oxygen_z REAL,
  anomaly_score REAL, is_anomaly INTEGER, label TEXT,
  station_lat REAL, station_lon REAL
);

CREATE TABLE alerts (
  id INTEGER PRIMARY KEY,
  timestamp TEXT, zone TEXT,
  urgency TEXT, threat TEXT, narrative TEXT,
  temp_c REAL, salinity REAL, dissolved_oxygen REAL,
  station_lat REAL, station_lon REAL
);
```

---

### 4.3 Demo Server — `bridge/demo_recording.py`

**Location:** `bridge/demo_recording.py`

A self-contained Flask server for hardware-free live demonstrations. It replays a scripted 60-second sensor cycle that visually showcases every system feature without any Arduino or AWS credentials.

**Scripted phases (cosine-interpolated):**

| Time | Phase | What Happens |
|---|---|---|
| 0–15s | Warm-up | Stable 17°C baseline, calm |
| 15–30s | Cold Plunge | Temperature drops to 7°C (upwelling simulation) |
| 30–45s | Recovery | Gradual return to baseline |
| 45–50s | Turbulence Spike | 1.8 m/s² jitter — entire 3D point cloud vibrates |
| 50–60s | Cooldown | Returns to calm; cycle repeats |

**Anomaly trigger:**
```python
is_anomaly = abs(temp - 14.2) > 3.6 or turbulence > 1.0
```

**Gemini integration:** If `GEMINI_KEY` is set, generates a scientific insight every 30s from the last 10 readings. Otherwise returns "Awaiting data stabilization…"

**Endpoints:** `/live`, `/x-feed` (returns 5 hardcoded demo tweets about red tide, fish kills, and kelp thinning)

---

### 4.4 Data Scripts

#### `data/build_baseline.py`

Builds the 12-month climatological baseline from raw CalCOFI CSVs.

- Input: `194903-202105_Bottle.csv` + `194903-202105_Cast.csv`
- Joins on `Cst_Cnt` (cast ID), filters depth < 200m
- Outputs: `calcofi_relevant.csv`, `baselines.json`

**Output schema (one entry per month):**
```json
{
  "month": 4,
  "temp_mean": 12.6935, "temp_std": 2.725,
  "sal_mean": 33.6121,  "sal_std": 0.4101,
  "oxygen_mean": 4.6824, "oxygen_std": 1.4448,
  "ph_mean": 7.8809,    "ph_std": 0.1149
}
```

#### `data/build_replay.py`

Extracts the October 2015 California Current marine heatwave as a 65-row hourly replay sequence.

- Filters to 27–38°N, 115–125°W
- Event window: 2015-10-29 to 2015-10-31
- Resamples aggregated observations to 1-hour grid via linear interpolation
- Output: `mooring_replay.csv`

#### `data/build_zone_artifacts.py`

Generates zone-specific baselines and synthetic anomaly replay sequences for three San Diego zones:

| Zone | Lat | Lon | Radius |
|---|---|---|---|
| Del Mar | 32.96°N | 117.28°W | 0.08° |
| Point Loma | 32.66°N | 117.25°W | 0.12° |
| South Bay | 32.56°N | 117.17°W | 0.15° |

Key step: **Anomaly pulse injection** — the real 2015 heatwave data is overlaid onto a zone-normalized timeline using a Gaussian weight function that peaks at the event center and tapers at the edges. This creates a physically motivated, zone-specific replay that still anchors to real historical extremes.

Output: `zone_baselines.json` (3 × 12 = 36 rows), `zone_replays.json` (3 × 36 timesteps = 108 rows)

#### `data/generate_splats.py`

Generates the 25,000-point Gaussian splatting dataset for 3D rendering.

**Path A (real data):** Fetches Argo float profiles from Scripps ERDDAP via `argopy` for the California Current region (2020–2024). Converts depth/temperature/salinity profiles to normalized (x, y, z) space.

**Path B (synthetic, default):** Procedurally generates a physically plausible California Current point cloud:
- Surface (0–50m): ~16°C, decreasing ~0.12°C per degree northward
- Thermocline (50–200m): sharp ~9°C drop
- Deep (>200m): cold 5–8°C uniform
- Random marine heatwave blobs (+2–4°C)
- Upwelling cold tongues near coast (−2.5°C)

Output schema per point:
```json
{"x": -0.123, "y": 0.456, "z": -0.789, "temp": 14.2, "sal": 33.5, "anomaly": 0.25, "scale": 0.0045}
```

#### `data/train_model.py`

Trains the global Isolation Forest anomaly detector.

1. Load baselines + `calcofi_relevant.csv`
2. Compute 3D z-score features: `[temp_z, sal_z, oxygen_z]`
3. Trim to "normal core": keep rows with all |z| ≤ 0.65σ
4. Train: `IsolationForest(n_estimators=300, contamination=0.25, n_jobs=-1)`
5. Evaluate on 2015 heatwave replay
6. Output: `isolation_forest.pkl`

#### `data/train_zone_models.py`

Same pipeline as above, per zone. Uses a slightly relaxed normal core threshold (`NORMAL_CORE_SIGMA = 0.9`) and fewer estimators (250) to account for smaller zone-level training sets.

Output: `zone_models.pkl` — a dict `{zone_name: IsolationForest}`

---

### 4.5 Frontend — `frontend/index.html`

**Location:** `frontend/index.html`

A ~1900-line self-contained single-page application. No build step required — served directly by Flask.

**Libraries (CDN):**
- Three.js r128 (3D rendering)
- MapLibre-GL (2D satellite map)
- All other logic in vanilla JS

#### View Modes

**2D Map View:**
- CartoDB Dark Matter basemap (water layer removed for transparency)
- Zone markers with pulsing CSS animations
- Click a zone marker → select zone + optionally dive to 3D view

**3D Underwater View:**
- 25,000-point Gaussian splat point cloud loaded from `splats.json`
- Procedural zone geometry: ring + core circle + stalk + pinging ring
- Camera: spherical coordinates, mouse-drag orbit, scroll-to-zoom
- `selectZone()` flies camera to the chosen zone

#### GLSL Shaders

**Vertex shader** — `oceanVert`:
- Per-vertex: position, `aAnomaly`, `aTemp`, `aSal` attributes
- Sine/cosine wave displacement for animated water motion
- Fixed point size of 6.2 px
- Passes `vAnomaly`, `vTemp`, `vSal` to fragment stage

**Fragment shader** — `oceanFrag`:
- Four visualization modes (toggled by `uMode` uniform):
  - **0 Heat:** anomaly → cold blue → warm orange → hot red
  - **1 Kelp:** green (healthy) → orange (stressed)
  - **2 Urchin:** purple → magenta (density)
  - **3 Salinity:** blue → yellow gradient
- Circle SDF for smooth point rendering; `discard` outside circle
- Additive blending for luminous glow effect
- `uAlert` uniform triggers visual pulse on anomaly events

#### Risk Scoring (JavaScript)

```javascript
function zoneRiskSummary(zoneId, live) {
  // kelp health proxy:
  let health = BASE_HEALTH
    - temp_risk   * 18   // heat stress on kelp
    - oxygen_stress * 11 // hypoxia damage
    - salinity_dev  * 4  // freshening stress
    - model_severity * 22; // IF anomaly severity

  // urchin pressure proxy:
  let pressure = BASE_PRESSURE
    + temp_risk     * 12 // warmer water favors urchins
    + model_severity * 18
    - oxygen_stress  * 8; // hypoxia suppresses urchins

  return {health, pressure, status, description};
}
```

#### Data Loop

```javascript
// Polls backend every 1500ms
async function refreshLive() {
  const zones = await fetch(`${API_BASE}/zones/live?_ts=${Date.now()}`).then(r => r.json());
  DashboardState.zoneStates = zones;
  renderZoneList();         // zone health/pressure cards
  updateInsightPanel();     // big temp + AI narrative
  updateChart(live.temp_c); // 36-point sparkline
  updateSignalsPanel();     // raw metric readouts
}

// Alert polling every 5000ms
async function refreshAlert() {
  const alert = await fetch(`${API_BASE}/alert/latest`).then(r => r.json());
  if (alert.active) { showAlertBadge(alert); }
}
```

---

## 5. Algorithms & Models

### Isolation Forest

Isolation Forest is an unsupervised anomaly detection algorithm that isolates anomalies by recursively partitioning features. Anomalies are isolated in fewer splits (shorter path length) → lower decision function scores.

**Feature space:** `[temp_z, sal_z, oxygen_z]` — z-scores against the current month's CalCOFI baseline. This makes the model invariant to seasonal temperature cycles.

**Training strategy:** Train only on "normal core" data (|z| ≤ 0.65σ for all features) so the model learns a tight boundary around historical normal. This is key — training on the full dataset would mute the anomaly signal.

**Scoring:** `model.decision_function(X)` returns a signed score. More negative = more anomalous.

### Z-Score Baselines

For each reading at month `m`:
```
temp_z = (temp_c - baselines[m].temp_mean) / baselines[m].temp_std
```

The 75-year CalCOFI dataset gives robust monthly means and standard deviations. Zone-specific baselines computed from spatially-filtered subsets give tighter distributions and more sensitive detection.

### Zone Stress Metric (for event selection)

When building zone replays, the most anomalous historical window is found by:
```
stress = max(temp_z, 0) + max(-oxygen_z, 0) + 0.5 * |sal_z|
```
This prioritizes warming + deoxygenation — the classic paired signature of a marine heatwave.

---

## 6. API Reference

All endpoints served by `bridge.py` (default: `http://localhost:5000`).

| Endpoint | Method | Returns |
|---|---|---|
| `/live` | GET | Current sensor state: `{temp_c, salinity, dissolved_oxygen, temp_z, sal_z, oxygen_z, anomaly_score, label, is_anomaly, station_lat, station_lon, timestamp}` |
| `/zones/live` | GET | Dict of all zone states: `{zone_id: state_dict}` |
| `/alert/latest` | GET | `{active: bool, urgency, threat, narrative, timestamp}` |
| `/history` | GET | Last 100 readings from SQLite |
| `/baseline` | GET | Current month's CalCOFI baseline stats |
| `/health` | GET | System status: `{gemini_configured, replay_rows, zone_count, data_sources}` |
| `/<path>` | GET | Serves `frontend/` static files |

---

## 7. Environment & Dependencies

### `.env.example`

```bash
GEMINI_KEY=          # Required — Google AI Studio key
ELEVENLABS_KEY=      # Optional — TTS voice alerts
ELEVENLABS_VOICE_ID= # Optional
AWS_ACCESS_KEY_ID=   # Optional — S3 archival
AWS_SECRET_ACCESS_KEY=
AWS_REGION=
S3_ALERTS_BUCKET=
S3_LIVE_BUCKET=
BEARER_TOKEN=        # Optional — X/Twitter social feed
ARDUINO_PORT=        # Optional — e.g. /dev/cu.usbmodem1234
```

Only `GEMINI_KEY` is required for full AI features. Everything else degrades gracefully.

### `requirements.txt` (key packages)

| Package | Version | Role |
|---|---|---|
| `flask` | ≥3.0.0 | Web framework |
| `flask-cors` | ≥4.0.0 | CORS for frontend dev |
| `boto3` | ≥1.28.0 | AWS S3 client |
| `google-genai` | ≥1.0.0 | Gemini API |
| `python-dotenv` | ≥1.0.0 | `.env` loading |
| `argopy` | ≥0.1.14 | Argo float ERDDAP client |
| `pandas` | ≥2.0.0 | Data wrangling |
| `numpy` | ≥1.24.0 | Numerical ops |
| `scikit-learn` | ≥1.3.0 | Isolation Forest |
| `joblib` | ≥1.3.0 | Model serialization |
| `marimo` | ≥0.3.0 | Interactive notebooks |
| `altair` | ≥5.0.0 | Declarative charts |

---

## 8. Running the System

### Option A: Full Stack (with Arduino)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set up environment
cp .env.example .env
# Edit .env and add GEMINI_KEY, ARDUINO_PORT, etc.

# 3. Flash Arduino
# Open hardware/sentinel_firmware/sentinel_firmware.ino in Arduino IDE
# Board: Arduino Uno R4 WiFi
# Upload → open Serial Monitor @ 9600 baud to verify JSON output

# 4. Run backend (reads serial + serves API)
cd bridge
python bridge.py

# 5. Open frontend
open frontend/index.html
# Or let Flask serve it: http://localhost:5000
```

### Option B: Demo Mode (no hardware needed)

```bash
# Runs scripted 60-second cycle — no Arduino, no AWS required
cd bridge
python demo_recording.py

# Open frontend/index.html
# The 2D map + 3D visualizer will show the cold plunge and turbulence spike
```

### Rebuilding Data Artifacts

Only needed if you change the source CalCOFI data or model parameters:

```bash
cd data
python build_baseline.py          # → baselines.json, calcofi_relevant.csv
python build_replay.py            # → mooring_replay.csv
python build_zone_artifacts.py    # → zone_baselines.json, zone_replays.json
python train_model.py             # → isolation_forest.pkl
python train_zone_models.py       # → zone_models.pkl
python generate_splats.py --synthetic  # → ../frontend/splats.json
```

Pre-built artifacts are committed and also available on S3 — no need to rebuild for normal development.

---

*Last updated: April 2026. Source of truth is the code; this document summarizes the state of the `rishab` branch.*
