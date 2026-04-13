"""
CAN bus telemetry extraction from nuScenes.

vehicle_monitor message fields used:
    utime         — Unix time in microseconds
    vehicle_speed — speed in m/s
    long_accel    — longitudinal acceleration in m/s²
    brake_state   — 0 or 1
"""

import warnings
from typing import Any


_DEFAULT_TELEMETRY = {
    "speed_kmh": 0.0,
    "braking": False,
    "acceleration_ms2": 0.0,
}

_DEFAULT_SUMMARY = {
    "avg_speed_kmh": 0.0,
    "max_decel_ms2": 0.0,
    "braking_detected": False,
    "speed_trend": "steady",
}


def load_can_telemetry(nusc_can: Any, scene_name: str) -> list[dict]:
    """
    Load the vehicle_monitor CAN messages for `scene_name`.

    Returns the raw list of message dicts on success, or an empty list with a
    warning if no CAN data is available for this scene.
    """
    try:
        messages = nusc_can.get_messages(scene_name, "vehicle_monitor")
        return messages
    except Exception as exc:
        warnings.warn(
            f"CAN bus data unavailable for '{scene_name}': {exc}. "
            "Falling back to default telemetry."
        )
        return []


def get_telemetry_at_timestamp(can_data: list[dict], timestamp_us: int) -> dict:
    """
    Find the CAN message closest in time to `timestamp_us` and return a
    normalised telemetry dict.

    Returns default telemetry if `can_data` is empty.
    """
    if not can_data:
        return dict(_DEFAULT_TELEMETRY)

    closest = min(can_data, key=lambda m: abs(m["utime"] - timestamp_us))

    speed_kmh = round(closest.get("vehicle_speed", 0.0) * 3.6, 1)
    accel = round(closest.get("long_accel", 0.0), 2)
    brake_state = closest.get("brake_state", 0)
    braking = bool(brake_state == 1 or accel < -1.5)

    return {
        "speed_kmh": speed_kmh,
        "braking": braking,
        "acceleration_ms2": accel,
    }


def summarize_window_telemetry(can_data: list[dict], window_frames: list[dict]) -> dict:
    """
    Aggregate telemetry across all frames in a window.

    Returns:
        avg_speed_kmh     — mean speed over the window
        max_decel_ms2     — most negative acceleration seen (0 if no decel)
        braking_detected  — True if any frame had braking
        speed_trend       — "accelerating" | "decelerating" | "steady"
    """
    if not window_frames:
        return dict(_DEFAULT_SUMMARY)

    telemetries = [
        get_telemetry_at_timestamp(can_data, f["timestamp_us"])
        for f in window_frames
    ]

    speeds = [t["speed_kmh"] for t in telemetries]
    accels = [t["acceleration_ms2"] for t in telemetries]

    avg_speed = round(sum(speeds) / len(speeds), 1)
    max_decel = round(min(accels), 2)  # most negative value
    braking_detected = any(t["braking"] for t in telemetries)

    # Speed trend: compare first vs last frame speed with a 2 km/h dead-band
    delta = speeds[-1] - speeds[0]
    if delta > 2.0:
        speed_trend = "accelerating"
    elif delta < -2.0:
        speed_trend = "decelerating"
    else:
        speed_trend = "steady"

    return {
        "avg_speed_kmh": avg_speed,
        "max_decel_ms2": max_decel,
        "braking_detected": braking_detected,
        "speed_trend": speed_trend,
    }
