"""
DriveVLM-Style Explanation Generator — nuScenes
================================================
Entry point. Orchestrates the full pipeline:
    scene loading → CAN telemetry → GPT-4o API → video rendering

Usage:
    OPENAI_API_KEY=<key> python main.py

The OpenAI client reads OPENAI_API_KEY automatically from the environment.
"""

import os

from openai import OpenAI
from nuscenes.nuscenes import NuScenes
from nuscenes.can_bus.can_bus_api import NuScenesCanBus

from config import (
    NUSCENES_DATAROOT,
    NUSCENES_VERSION,
    SCENE_NAME,
    FRAMES_PER_WINDOW,
    OUTPUT_DIR,
)
from scene_loader import load_scene_frames, assign_windows
from can_loader import load_can_telemetry
from explainer import generate_all_explanations
from video_writer import write_both_videos


def main() -> None:
    # ------------------------------------------------------------------
    # 1. Initialise datasets and API client
    # ------------------------------------------------------------------
    print(f"Loading nuScenes {NUSCENES_VERSION} from {NUSCENES_DATAROOT} ...")
    nusc = NuScenes(version=NUSCENES_VERSION, dataroot=NUSCENES_DATAROOT, verbose=False)

    print("Loading CAN bus database ...")
    try:
        nusc_can = NuScenesCanBus(dataroot=NUSCENES_DATAROOT)
    except Exception as e:
        print(f"  CAN bus not available ({e}). Continuing without telemetry.")
        nusc_can = None

    client = OpenAI()  # reads OPENAI_API_KEY from environment

    # ------------------------------------------------------------------
    # 2. Load frames for the selected scene
    # ------------------------------------------------------------------
    print(f"\nScene: {SCENE_NAME}")
    print("Use nusc.list_scenes() to browse available scenes.\n")

    frames = load_scene_frames(nusc, SCENE_NAME)

    # ------------------------------------------------------------------
    # 3. Assign frames to windows
    # ------------------------------------------------------------------
    windows, frame_to_window_map = assign_windows(frames, FRAMES_PER_WINDOW)

    total_api_calls = len(windows) * 2  # descriptive + teleological per window
    print(
        f"Summary:\n"
        f"  Scene:          {SCENE_NAME}\n"
        f"  Total frames:   {len(frames)}\n"
        f"  Window size:    {FRAMES_PER_WINDOW} frames\n"
        f"  Total windows:  {len(windows)}\n"
        f"  API calls:      {total_api_calls} (2 per window)\n"
    )

    # ------------------------------------------------------------------
    # 4. Load CAN telemetry
    # ------------------------------------------------------------------
    can_data = load_can_telemetry(nusc_can, SCENE_NAME) if nusc_can is not None else []
    if can_data:
        print(f"CAN bus messages loaded: {len(can_data)}")
    else:
        print("CAN bus unavailable — using default telemetry fallback.")

    # ------------------------------------------------------------------
    # 5. Generate all explanations (slow — 2 × n_windows API calls)
    # ------------------------------------------------------------------
    print("\nGenerating explanations via Claude Vision API ...")
    explanations = generate_all_explanations(client, windows, can_data, SCENE_NAME, nusc_can)

    # ------------------------------------------------------------------
    # 6. Print all explanations for review
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("GENERATED EXPLANATIONS")
    print("=" * 70)
    for exp in explanations:
        win_i = exp["window_index"]
        tel = exp["telemetry"]
        print(
            f"\nWindow {win_i + 1}  "
            f"[{tel['avg_speed_kmh']} km/h | "
            f"braking={tel['braking_detected']} | "
            f"{tel['speed_trend']}]"
        )
        print(f"  DESCRIPTIVE:   {exp['descriptive']}")
        print(f"  TELEOLOGICAL:  {exp['teleological']}")
    print("=" * 70 + "\n")

    # ------------------------------------------------------------------
    # 7. Create output directory
    # ------------------------------------------------------------------
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # ------------------------------------------------------------------
    # 8. Render both MP4 videos
    # ------------------------------------------------------------------
    write_both_videos(frames, explanations, frame_to_window_map, OUTPUT_DIR)

    print(
        "\nDone. Videos written to "
        "outputs/descriptive.mp4 and outputs/teleological.mp4"
    )


if __name__ == "__main__":
    main()
