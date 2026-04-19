<<<<<<< HEAD
<p align="center">
  <h1 align="center">🌊 AEGIS OCEAN</h1>
  <p align="center"><strong>The Democratic Ocean Sentinel</strong></p>
  <p align="center">
    Real-time 3D Gaussian Splatting · Arduino Modulino Sensors · Gemini AI Insights
    <br/>
    <em>DS3 @ UCSD · DataHacks 2026 · April 18–19</em>
  </p>
</p>

---

A decentralized, community-deployable ocean health network — pairing an **Arduino Modulino Sentinel** (temperature + distance + movement) with **70+ years of Scripps/CalCOFI training data** and a live **3D Gaussian Splatting visualization**, making invisible climate crises visceral and actionable for anyone on the water.

## Core Features

| Feature | Description |
|---------|-------------|
| **Real-time WebGL Gaussian Splats** | 25,000-point volumetric point cloud of the California Current rendered via Three.js with custom GLSL shaders. Heatmap dynamically shifts based on live temperature data. |
| **Turbulence-Reactive 3D Scene** | Shader-driven vertex displacement jitters the entire point cloud proportional to real-time turbulence readings — the ocean literally vibrates when disturbed. |
| **Gemini-Powered Scientific Insights** | Every 30 seconds, a rolling buffer of 10 sensor readings is sent to Google Gemini, which returns a one-sentence professional oceanographic insight displayed with a typewriter animation. |
| **Turbulence Alert System** | Sudden turbulence spikes trigger a full-screen red pulse in the 3D scene. Anomalies (2+ σ from CalCOFI baselines) fire Gemini alert summaries + ElevenLabs TTS voice alerts uploaded to S3. |
| **Sensor Calibration** | One-click "zero" calibration button in the UI resets all sensor baselines for field deployment. |
| **Simulated Mode Badge** | When running without hardware, a `SIMULATED MODE` badge appears automatically so demo audiences know the data source. |
| **X (Twitter) Social Feed** | Sidebar streams real-time social signals for algae blooms, red tide, and fish kills along the California coast. |

---

## System Architecture

```
┌─────────────────────┐
│  Arduino Modulino   │
│  ┌───────────────┐  │
│  │ Thermo Module │──┤── Temperature (°C)
│  │ Distance      │──┤── Water Level (mm)
│  │ Movement/IMU  │──┤── Turbulence (m/s²)
│  └───────────────┘  │
└─────────┬───────────┘
          │ USB Serial (JSON @ 9600 baud)
          ▼
┌─────────────────────┐     ┌──────────────────┐
│   bridge.py (Flask) │────▶│  Google Gemini    │
│                     │     │  ┌──────────────┐ │
│  • Serial reader    │     │  │ Alert Summary│ │
│  • Anomaly detection│     │  │ Sci. Insight │ │
│  • /live endpoint   │     │  └──────────────┘ │
│  • /x-feed endpoint │     └──────────────────┘
│  • S3 archival      │
│  • Insight buffer   │     ┌──────────────────┐
│                     │────▶│  ElevenLabs TTS  │──▶ S3 MP3
└─────────┬───────────┘     └──────────────────┘
          │ HTTP poll (3s)
          ▼
┌─────────────────────┐
│  Frontend (Three.js)│
│                     │
│  • 3D Gaussian Splat│
│  • GLSL heatmap     │
│  • Sensor Feeds UI  │
│  • Typewriter AI    │
│  • Turb. red pulse  │
│  • Calibration btn  │
└─────────────────────┘
```

### Data Flow

1. **Arduino** reads Thermo/Distance/Movement modules every 3 seconds and emits JSON over USB serial.
2. **bridge.py** parses the serial stream, runs anomaly detection against CalCOFI 75-year monthly baselines, and exposes the latest state on `GET /live`.
3. On anomaly, **Gemini** generates a 2-sentence plain-language alert; **ElevenLabs** converts it to speech; the MP3 is uploaded to **S3**.
4. Every 30 seconds, the last 10 readings are sent to **Gemini** for a professional oceanographic insight.
5. The **frontend** polls `/live` every 3 seconds and pushes `uTurbulence` and `uTemperature` into the GLSL shaders, making the 3D scene physically reactive to the ocean.

---

## Project Structure

```
datahacks/
├── bridge/
│   ├── bridge.py              # Flask API — serial reader + Gemini + S3
│   └── demo_recording.py      # Hardware-free demo with scripted sequences
├── data/
│   └── generate_splats.py     # Synthetic 25K-point CalCOFI splat generator
├── frontend/
│   ├── index.html             # Three.js 3D scene + UI + GLSL shaders
│   └── splats.json            # Generated Gaussian splat dataset
├── hardware/
│   └── sentinel_firmware/
│       └── sentinel_firmware.ino  # Arduino Modulino sketch
├── .env.example               # Environment variable template
├── .gitignore
├── requirements.txt
└── README.md
```

---

## Setup

### Prerequisites

- **Python 3.10+**
- **Node.js** (optional — only needed if you extend the frontend)
- **Arduino IDE 2.x** (only if flashing hardware)

### 1. Clone & Install

```bash
git clone https://github.com/your-org/datahacks.git
cd datahacks
pip install -r requirements.txt
```

### 2. Configure Environment Variables

```bash
cp .env.example .env
```

Open `.env` and fill in:

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_KEY` | ✅ | Google AI Studio API key for insights & alerts |
| `ELEVENLABS_KEY` | ⬜ | ElevenLabs TTS key (alerts degrade gracefully without it) |
| `ELEVENLABS_VOICE_ID` | ⬜ | Voice ID (defaults to "Rachel") |
| `AWS_ACCESS_KEY_ID` | ⬜ | For S3 archival (skipped silently if missing) |
| `AWS_SECRET_ACCESS_KEY` | ⬜ | For S3 archival |
| `AWS_REGION` | ⬜ | Defaults to `us-west-2` |
| `BEARER_TOKEN` | ⬜ | X/Twitter API bearer token for social feed |
| `ARDUINO_PORT` | ⬜ | USB serial port — e.g. `/dev/cu.usbmodem14201` |

> **Minimum viable:** Only `GEMINI_KEY` is needed for the full demo experience. Everything else degrades gracefully.

### 3. Generate Splat Data

```bash
python data/generate_splats.py
```

This creates `frontend/splats.json` (~2.3 MB, 25,000 synthetic CalCOFI-based points).

### 4. Launch

**Terminal 1 — Backend:**
```bash
# Live mode (with Arduino plugged in):
python bridge/bridge.py

# Demo mode (no hardware needed):
python bridge/demo_recording.py
```

**Terminal 2 — Frontend:**
```bash
cd frontend
python -m http.server 8080
```

Open **http://localhost:8080** — the 3D scene loads immediately with demo splats, and sensor data starts streaming within 3 seconds.

---

## Demo Mode

`bridge/demo_recording.py` runs a scripted high-intensity data sequence designed to showcase every visual feature:

| Phase | Duration | What Happens |
|-------|----------|--------------|
| **Warm-up** | 0–15s | Stable ~17°C baseline readings |
| **Temperature Drop** | 15–30s | 10°C plunge simulating cold upwelling — watch the heatmap shift to deep blues |
| **Recovery** | 30–45s | Gradual return to baseline |
| **Turbulence Spike** | 45–50s | 5-second burst at 1.8 m/s² — the entire point cloud vibrates and the background pulses red |
| **Cooldown** | 50–60s | Return to calm; cycle repeats |

No API keys are required for the visual demo. If `GEMINI_KEY` is set, Gemini insights will also generate during the sequence.

---

## Hardware Setup

### Arduino Modulino Kit

1. Open `hardware/sentinel_firmware/sentinel_firmware.ino` in Arduino IDE 2.x
2. Install the **Modulino** library via Library Manager
3. Select your board and port
4. Upload the sketch
5. Run `ls /dev/cu.*` (macOS) to find the port, then set `ARDUINO_PORT` in `.env`

### Serial Output Format

```json
{"temp": 17.2, "distance_mm": 104.5, "turbulence": 0.23}
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Hardware | Arduino UNO R4 WiFi + Modulino (Thermo, Distance, Movement) |
| Backend | Python 3.10, Flask, PySerial |
| AI | Google Gemini 1.5 Flash |
| Voice | ElevenLabs v1 TTS |
| Storage | AWS S3 |
| Frontend | Three.js r128, Custom GLSL shaders |
| Data | Scripps/CalCOFI 75-year baselines, Argo float profiles |

---

## Team

**404 Fish Now Found** — DS3 @ UCSD, DataHacks 2026

<p align="center">
  <em>Making invisible climate crises visceral and actionable.</em>
</p>

---

## Technical Analytics & Documentation

### Notebooks & Exports (Marimo/Databricks)
We harness local analytics to bridge raw SQLite metrics with data visualization using the **Marimo** reactive notebook framework alongside **Databricks**. Check the `/notebooks` folder for the Python scripts representing these pipelines.
To export dynamic HTML summaries directly into `/docs` for offline presentation, execute:
```bash
marimo export html notebooks/analytics.py > docs/analytics.html
```

### Scientific Methodology
* **Z-Score Normalization**: To identify significant anomalies in real-time sensor streams without arbitrary hardcoding, we explicitly apply $Z$-Score scaling using $Z = \frac{X - \mu}{\sigma}$ relative to monthly Scripps historical means.
* **Isolation Forest**: CalCOFI baseline metrics map into an Isolation Forest model (trained via PySpark on Databricks architecture). Because kelp degradation is typically a multivariate crisis involving both temperature elevation and oxygen depletion simultaneously, the Isolation Forest dynamically cuts dimensional planes identifying distinct profile irregularities ($score < -0.1$), triggering Gemini when ecosystems breach tolerance.

## Dataset Citations
We explicitly acknowledge the Scripps Institution of Oceanography for their rigorous historical modeling underpinning this project's predictive capabilities:
1. **CalCOFI (California Cooperative Oceanic Fisheries Investigations):** Providing the 75-year multi-feature regional baselines.
2. **CCE LTER (California Current Ecosystem):** Point sensor metrics used directly inside our temporal replay mechanisms.
3. **EasyOneArgo:** Point cloud generation data fueling our high-fidelity WebGL Gaussian Splat spatial projections.
