# AdaptTrust — Explainability in Autonomous Vehicles
**CS 6170 AI Capstone | Meet Jain & Yash Phalle | Prof. Stacy Marsella | Target: CHI 2026**

> Do LLM-generated explanations of autonomous vehicle actions improve passenger trust calibration?

---

## Table of Contents
1. [Project Overview](#project-overview)
2. [System Requirements](#system-requirements)
3. [Verified Hardware](#verified-hardware)
4. [Setup](#setup)
5. [Running the Pipeline](#running-the-pipeline)
6. [Scenarios](#scenarios)
7. [Project Structure](#project-structure)
8. [Output Files](#output-files)
9. [Environment Variables](#environment-variables)
10. [Git Workflow](#git-workflow)
11. [Known Issues](#known-issues)

---

## Project Overview

AdaptTrust records autonomous vehicle scenarios in CARLA, generates LLM-powered explanations for each critical driving event, and overlays them onto video. These videos are shown to study participants to measure how explanation type affects trust calibration.

**Three explanation conditions:**

| # | Type | Description |
|---|---|---|
| 1 | None | No explanation shown (control) |
| 2 | LLM-Descriptive | GPT-4o factual description of what the vehicle is about to do |
| 3 | LLM-Teleological | GPT-4o goal-oriented explanation of why the vehicle is acting |

**GPT-4o context per explanation:**
- Every 4th trigger frame sent as images (multi-frame visual context)
- Vehicle telemetry: speed, brake, throttle, steer
- YOLO-detected objects with confidence scores
- Traffic light state (inferred from YOLO + braking behaviour)
- Nearest NPC: type, distance, speed (from `npc_telemetry.json`)
- Anticipatory framing — explanation appears **2 seconds before** the action fires

**Metrics:** Jian Trust Scale (12-item), Comprehension accuracy, Mental Model Quality (0–4, Cohen's κ > 0.70), NASA-TLX cognitive load.

---

## System Requirements

| Component | Minimum | Recommended |
|---|---|---|
| OS | Ubuntu 20.04 | Ubuntu 22.04 LTS |
| GPU | NVIDIA RTX 2070 (6 GB VRAM) | NVIDIA RTX 3080+ (8 GB+ VRAM) |
| RAM | 16 GB | 32 GB |
| Disk | 30 GB free | 50 GB+ free |
| Python | 3.10 | 3.10 |
| NVIDIA Driver | 525+ | 580+ |

> **RTX 5060 / Blackwell users:** Requires Ubuntu kernel 6.8+. MESA warnings about unknown PCI IDs are harmless — CARLA uses the NVIDIA proprietary driver, not Mesa.

---

## Verified Hardware

Meet's machine (fully tested):

```
Model:   Lenovo Legion 7 16IAX10
CPU:     Intel Core Ultra 7 255HX
GPU:     NVIDIA GeForce RTX 5060 Laptop (8 GB, Blackwell)
RAM:     32 GB
OS:      Ubuntu 22.04.5 LTS, Kernel 6.8.0
Driver:  580.126.09
```

---

## Setup

### 1. Install Miniconda

```bash
cd ~
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O miniconda.sh
bash ~/miniconda.sh -b -p ~/miniconda3
~/miniconda3/bin/conda init bash
source ~/.bashrc
```

### 2. Accept Conda Terms of Service (conda 25+)

```bash
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r
```

### 3. Restore the environment

```bash
cd ~/xav
conda env create -f carla-xav-environment.yml
conda activate carla-xav
```

> This reproduces the exact package versions used during development. Prefer this over installing manually.

### 4. Isolate from ROS PYTHONPATH (ROS users only)

```bash
conda activate carla-xav
conda env config vars set PYTHONPATH=""
conda deactivate && conda activate carla-xav
echo $PYTHONPATH   # should be empty
```

### 5. Download CARLA 0.9.15

> The GitHub release links for CARLA 0.9.15 are broken. Use this Backblaze URL directly:

```bash
mkdir -p ~/carla && cd ~/carla
wget "https://carla-releases.s3.us-east-005.backblazeb2.com/Linux/CARLA_0.9.15.tar.gz"
tar -xvzf CARLA_0.9.15.tar.gz
```

Expected contents after extraction: `CarlaUE4.sh`, `CarlaUE4/`, `PythonAPI/`, `HDMaps/`

### 6. Set up API key

```bash
cp .env.example .env
# edit .env and add your OpenAI key:
# OPENAI_API_KEY=sk-...
```

### 7. Verify the setup

```bash
conda activate carla-xav
python -c "import carla; print('carla ok')"
python -c "import torch; print(torch.__version__)"
python -c "import ultralytics; print('yolo ok')"
python -c "import openai; print('openai ok')"
python -c "from scripts.scenarios.adaptrust_scenarios import SCENARIO_REGISTRY; print(sorted(SCENARIO_REGISTRY))"
```

---

## Running the Pipeline

One command does everything: records the scenario, runs YOLO detection, calls GPT-4o for explanations, and renders all overlay videos.

### Terminal 1 — Start CARLA

```bash
cd ~/carla
./CarlaUE4.sh -quality-level=Low
```

For development/testing use `-quality-level=Low`. For final data collection use `-quality-level=Epic`.

### Terminal 2 — Run a scenario

```bash
conda activate carla-xav
cd ~/xav
python scripts/run_adaptrust.py --scenario <SCENARIO_ID> --run <N>
```

CARLA will automatically load the correct map for the scenario. If it crashes on map switch (Blackwell GPU), start CARLA with the right map manually and add `--skip-map-reload`:

```bash
# Terminal 1: start on the right map
./CarlaUE4.sh -quality-level=Low +Map=Town02

# Terminal 2:
python scripts/run_adaptrust.py --scenario S1_JaywalkingAdult --run 1 --skip-map-reload
```

### What happens automatically

```
record scenario
    → YOLO detection on every frame
    → trigger events logged (BRAKING, ACCELERATING, TURNING)
    → trigger frames saved (JPEGs)
    → GPT-4o called with frames + telemetry + NPC context
    → explanations written (none.json, descriptive.json, teleological.json)
    → 3 overlay videos rendered (video_none.mp4, video_descriptive.mp4, video_teleological.mp4)
    → pass/fail verdict written
```

### Check the verdict

```bash
cat data/scenarios/H1_PedestrianDart_run1/scenario_verdict.json
```

If `PASSED` is `false`, the critical event didn't fire — re-run on the correct map.

### Inspect a run (optional)

```bash
python scripts/scene_logger.py data/scenarios/H1_PedestrianDart_run1
```

Prints a timestamped event log with speed, brake, YOLO detections, and explanation strings at each trigger point.

---

## Scenarios

13 scenarios across 4 maps:

| ID | Map | Criticality | Critical Event | Description |
|---|---|---|---|---|
| L1_GreenLightCruise | Town03 | LOW | — | Cruise at 40 km/h through all-green lights |
| L2_SlowLeadOvertake | Town04 | LOW | — | Slow lead vehicle at ~20 km/h; ego follows |
| L3_NarrowStreetNav | Town02 | LOW | — | Navigate past parked cars at 20 km/h |
| M1_YellowLightStop | Town03 | MEDIUM | BRAKING | TL turns yellow; ego soft-brakes |
| M2_CrosswalkYield | Town02 | MEDIUM | BRAKING | Pedestrian crosses; ego yields |
| M3_HighwayMergeYield | Town04 | MEDIUM | BRAKING | NPC merges from left; ego yields |
| H1_PedestrianDart | Town02 | HIGH | BRAKING | Child darts into road; ego emergency-brakes |
| H2_HighwayCutIn | Town04 | HIGH | BRAKING | NPC cuts in from behind; ego emergency-brakes |
| H3_RedLightRunner | Town03 | HIGH | BRAKING | NPC runs red from cross street; ego emergency-brakes |
| S1_JaywalkingAdult | Town02 | HIGH | BRAKING | Adult jaywalks mid-block; ego emergency-brakes |
| S2_SuddenStopEvasion | Town04 | HIGH | BRAKING | Lead vehicle stops suddenly; ego evades |
| S4_EmergencyVehiclePullOver | Town02 | HIGH | TURNING | Emergency vehicle approaches; ego pulls over |
| S5_HiddenCyclist | Town02 | HIGH | BRAKING | Cyclist emerges from blind spot; ego emergency-brakes |

**Final 5 scenarios used in study:** S1, S2, S4, S5, L3

---

## Project Structure

```
xav/
├── README.md
├── carla-xav-environment.yml          # Conda environment lock file
├── .env.example                       # API key template
├── .gitignore
│
├── scripts/
│   ├── run_adaptrust.py               # Entry point — one command runs full pipeline
│   ├── adaptrust_runner.py            # Core runner: spawns ego, sensors, tick loop,
│   │                                  #   calls explanation generator + overlay renderer
│   ├── scene_logger.py                # Diagnostic: print event log for a recorded run
│   │
│   ├── scenarios/
│   │   └── adaptrust_scenarios.py     # All 13 scenario classes + SCENARIO_REGISTRY
│   │
│   ├── data_collection/
│   │   └── recorder.py                # RGB recording, YOLO detection, trigger logging,
│   │                                  #   NPC telemetry, trigger frame capture
│   │
│   ├── explanation_gen/
│   │   └── generator.py               # GPT-4o multi-frame calls → 3 explanation variants
│   │                                  #   (none, descriptive, teleological)
│   │
│   ├── video_pipeline/
│   │   └── overlay.py                 # OpenCV HUD overlay → 3 output videos
│   │                                  #   explanations displayed 2s before trigger event
│   │
│   └── audio_pipeline/
│       └── synthesizer.py             # TTS voiceover + engine noise added to videos
│
├── survey/                            # Next.js survey webapp (Supabase backend)
│   │                                  #   Jian Trust Scale, NASA-TLX, comprehension,
│   │                                  #   consent, demographics
│   └── ...
│
├── data/
│   └── scenarios/                     # Recorded runs (not in git — too large)
│
├── analysis/
│   ├── survey/                        # Qualtrics survey design
│   └── stats/                         # R / Python mixed-effects models
│
└── paper/                             # CHI 2026 draft
```

---

## Output Files

Each `data/scenarios/<SCENARIO_ID>_run<N>/` directory contains:

| File | Description |
|---|---|
| `video.mp4` | Raw 1920×1080 recording |
| `telemetry.json` | Per-frame: speed, throttle, brake, steer, position |
| `npc_telemetry.json` | Per-frame position and speed of each NPC |
| `yolo_detections.json` | Per-frame YOLO detections with class, confidence, bbox |
| `action_events.json` | Trigger events with telemetry snapshots and frame paths |
| `scenario_verdict.json` | Pass/fail — whether the critical event fired |
| `trigger_frames/` | JPEG screenshots around each trigger (sent to GPT-4o) |
| `explanations/none.json` | Control condition — empty explanations |
| `explanations/descriptive.json` | GPT-4o factual descriptions |
| `explanations/teleological.json` | GPT-4o goal-oriented explanations |
| `video_none.mp4` | Overlay video — no explanation |
| `video_descriptive.mp4` | Overlay video — LLM descriptive |
| `video_teleological.mp4` | Overlay video — LLM teleological |

---

## Environment Variables

```bash
cp .env.example .env
```

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | For LLM conditions only | GPT-4o API key. Without it, descriptive and teleological conditions get placeholder text. |

---

## Git Workflow

Both contributors push to `main`. Always pull before starting work:

```bash
git pull origin main
# make changes
git add <files>
git commit -m "short description"
git push origin main
```

If there are conflicts, give priority to scenario scripts from the person who owns that scenario.

---

## Known Issues

| Issue | Notes |
|---|---|
| MESA warning `Driver does not support 0x7d67 PCI ID` | Harmless on RTX 5060. CARLA uses NVIDIA driver, not Mesa. |
| `client.load_world()` causes Signal 11 segfault | RTX 5060 / Blackwell only. Start CARLA with `+Map=<Town>` and use `--skip-map-reload`. |
| `nvidia-smi` shows CUDA 13.0, `nvcc` shows 11.5 | Irrelevant — project uses conda-managed CUDA. |
| CARLA 0.9.15 GitHub download links broken | Use the Backblaze URL in Setup Step 5. |

---

*AdaptTrust | HRI Team | CS 6170 AI Capstone | Northeastern University*
