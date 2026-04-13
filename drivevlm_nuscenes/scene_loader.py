"""
nuScenes scene selection and CAM_FRONT frame extraction.
"""

import os
from typing import Any

from config import NUSCENES_DATAROOT, FRAMES_PER_WINDOW


def load_scene_frames(nusc: Any, scene_name: str) -> list[dict]:
    """
    Walk the linked-list of samples for `scene_name` and collect every
    CAM_FRONT frame.

    Returns a list of dicts:
        {
            "frame_path":    str  — absolute path to the JPEG,
            "timestamp_us":  int  — sample timestamp in microseconds,
            "sample_token":  str  — nuScenes sample token,
        }
    """
    # Resolve scene token
    scene_token = nusc.field2token("scene", "name", scene_name)
    if not scene_token:
        raise ValueError(f"Scene '{scene_name}' not found in dataset.")
    scene = nusc.get("scene", scene_token[0])

    frames: list[dict] = []
    sample_token = scene["first_sample_token"]

    while sample_token:
        sample = nusc.get("sample", sample_token)
        cam_front_token = sample["data"]["CAM_FRONT"]
        sd = nusc.get("sample_data", cam_front_token)

        full_path = os.path.join(NUSCENES_DATAROOT, sd["filename"])
        frames.append(
            {
                "frame_path": full_path,
                "timestamp_us": sd["timestamp"],
                "sample_token": sample_token,
            }
        )

        sample_token = sample["next"]  # empty string signals end of scene

    return frames


def assign_windows(
    frames: list[dict],
    frames_per_window: int = FRAMES_PER_WINDOW,
) -> tuple[list[list[dict]], dict[int, int]]:
    """
    Group `frames` into consecutive windows of size `frames_per_window`.
    The last window may be smaller than the requested size.

    Returns:
        windows            — list of windows (each window is a list of frame dicts)
        frame_to_window    — dict mapping frame index → window index
    """
    windows: list[list[dict]] = []
    frame_to_window: dict[int, int] = {}

    for i in range(0, len(frames), frames_per_window):
        window = frames[i : i + frames_per_window]
        window_idx = len(windows)
        windows.append(window)
        for j, _ in enumerate(window):
            frame_to_window[i + j] = window_idx

    return windows, frame_to_window
