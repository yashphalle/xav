"""
overlay.py — Render explanation overlays + persistent HUD onto scenario videos.

Every output video (all 4 conditions, including none) shows:
  • TOP BAR    — detected object labels from YOLO for that frame
  • BOTTOM LEFT — speed (km/h) + colour-coded action state, always visible
  • BOTTOM CENTER — explanation text (condition-dependent, only when active)

Output files written alongside video.mp4:
    video_none.mp4
    video_template.mp4
    video_descriptive.mp4
    video_teleological.mp4

Usage:
    python scripts/video_pipeline/overlay.py data/scenarios/recorder_test_run1
    python scripts/video_pipeline/overlay.py data/scenarios/recorder_test_run1 --conditions template
"""

import argparse
import json
import sys
import textwrap
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

# Shared
FONT           = cv2.FONT_HERSHEY_SIMPLEX
HUD_ALPHA      = 0.60          # semi-transparent box opacity (all HUD elements)
COLOR_WHITE    = (255, 255, 255)
COLOR_DIM      = (160, 160, 160)

# Top bar — detected objects
TOP_BAR_FRAC   = 0.08          # height as fraction of frame (86 px at 1080p)
TOP_BAR_SCALE  = 0.65
TOP_BAR_THICK  = 2
TOP_BAR_PAD_Y  = 8             # px above/below text inside bar

# Speed / action box — bottom left
SPEED_SCALE    = 1.6           # large speed number
SPEED_THICK    = 3
STATE_SCALE    = 0.65          # smaller action state label
STATE_THICK    = 2
SPEED_BOX_PAD  = 14            # px inside speed box
SPEED_BOX_MARGIN = 18          # px from frame edge

# Action state colours (BGR)
_STATE_COLORS = {
    "BRAKING":      (50,  80,  255),   # red-orange
    "TURNING":      (0,   200, 255),   # yellow
    "ACCELERATING": (80,  210, 80),    # green
    "CRUISING":     (190, 190, 190),   # light grey
}

# Explanation text — bottom centre
EXPL_SCALE     = 0.8
EXPL_THICK     = 2
EXPL_WRAP      = 80            # chars per line
EXPL_PAD_X     = 20
EXPL_PAD_Y     = 12
EXPL_LINE_GAP  = 8
EXPL_AREA_TOP  = 0.80          # explanation stays in bottom 20% of frame

# How long (sim-seconds) each explanation is displayed
DISPLAY_BEFORE_S = 2.0
DISPLAY_AFTER_S  = 3.0

# Idle subtitle shown continuously on LLM conditions when no event is active
_IDLE_TEXT = {
    "descriptive":  "GPT-4o  |  Monitoring driving events…",
    "teleological": "GPT-4o  |  Monitoring driving events…",
}
COLOR_DIM_IDLE = (120, 120, 120)   # grey for idle subtitle text

# Output codec
FOURCC = cv2.VideoWriter_fourcc(*"mp4v")

CONDITIONS = ["none", "descriptive", "teleological"]

# Safety-relevant classes shown in the HUD top bar.
# Cars, trucks, buses, motorcycles are omitted — normal traffic, not notable.
# Traffic lights are always shown (colour not determinable from YOLO class alone).
_HUD_SAFETY_CLASSES = {
    "person":        "Pedestrian",
    "bicycle":       "Cyclist",
    "traffic light": "Traffic Light",
}


# ---------------------------------------------------------------------------
# Data preparation helpers
# ---------------------------------------------------------------------------

_VEHICLE_CLASSES = {"car", "truck", "bus", "motorcycle", "van"}


def _build_frame_yolo_map(detections: list[dict]) -> dict[int, list[str]]:
    """
    Build dict: frame_idx → sorted list of safety-relevant HUD labels for that frame.

    Only pedestrians, cyclists, and traffic lights are shown — normal traffic
    (cars, trucks, buses, motorcycles) is filtered out as non-notable.
    Sorted by descending max confidence so most prominent objects come first.
    """
    per_frame: dict[int, dict[str, float]] = {}
    for d in detections:
        cls = d["class_name"]
        if cls not in _HUD_SAFETY_CLASSES:
            continue                        # skip non-safety objects
        fi   = d["frame_idx"]
        conf = d.get("confidence", 0.0)
        if fi not in per_frame:
            per_frame[fi] = {}
        if conf > per_frame[fi].get(cls, 0.0):
            per_frame[fi][cls] = conf

    return {
        fi: [
            _HUD_SAFETY_CLASSES[cls]
            for cls, _ in sorted(cls_map.items(), key=lambda x: -x[1])
        ]
        for fi, cls_map in per_frame.items()
    }


def _build_frame_vehicle_map(detections: list[dict]) -> dict[int, bool]:
    """Return set of frame indices where a vehicle (car/truck/bus/motorcycle) was detected."""
    result: dict[int, bool] = {}
    for d in detections:
        if d["class_name"] in _VEHICLE_CLASSES:
            result[d["frame_idx"]] = True
    return result


def _derive_action_state(snap: dict) -> str:
    """Derive human-readable action state from a telemetry snapshot."""
    brake    = snap.get("brake",    0.0)
    throttle = snap.get("throttle", 0.0)
    steer    = snap.get("steer",    0.0)
    if brake > 0.30:
        return "BRAKING"
    if abs(steer) > 0.25:
        return "TURNING"
    if throttle > 0.50:
        return "ACCELERATING"
    return "CRUISING"


def _derive_action_text(snap: dict, yolo_labels: list[str],
                        has_vehicle: bool = False) -> str:
    """
    Always-on short action label for the bottom bar.
    Derived per-frame from telemetry + current YOLO labels.

    has_vehicle: True if YOLO detected a car/truck/bus in this frame (passed
                 separately because vehicles are filtered from HUD labels).
    """
    action         = _derive_action_state(snap)
    brake          = snap.get("brake", 0.0)
    steer          = snap.get("steer", 0.0)
    has_pedestrian = "Pedestrian"    in yolo_labels
    has_cyclist    = "Cyclist"       in yolo_labels
    has_tl         = "Traffic Light" in yolo_labels

    if action == "BRAKING":
        prefix = "Emergency brake!" if brake >= 0.8 else "Braking."
        if has_pedestrian:
            return f"{prefix} Pedestrian ahead."
        if has_cyclist:
            return f"{prefix} Cyclist ahead."
        if has_vehicle:
            return f"{prefix} Vehicle ahead."
        if has_tl:
            return f"{prefix} Red light."
        return prefix

    if action == "ACCELERATING":
        return "Accelerating. Green light." if has_tl else "Accelerating."

    if action == "TURNING":
        return "Turning right." if steer > 0 else "Turning left."

    if has_pedestrian:
        return "Pedestrian nearby. Monitoring."
    return "Cruising."


def _build_timestamp_index(telemetry: list[dict]) -> list[float]:
    return [e["timestamp"] for e in telemetry]


def _find_frame_for_time(timestamps: list[float], sim_time: float) -> int:
    lo, hi = 0, len(timestamps) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if timestamps[mid] < sim_time:
            lo = mid + 1
        else:
            hi = mid
    return max(0, min(lo, len(timestamps) - 1))


_TTS_WORDS_PER_SECOND = 2.5   # gTTS UK accent approximate rate

def _build_frame_text_map(
    events: list[dict],
    timestamps: list[float],
    before_s: float = DISPLAY_BEFORE_S,
    after_s:  float = DISPLAY_AFTER_S,
    fps: float = 30.0,
) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for event in events:
        explanation = event.get("explanation", "")
        if not explanation:
            continue

        if "audio_start_s" in event:
            # Explicit override: subtitle starts when audio starts
            start_vid  = float(event["audio_start_s"])
            word_count = len(explanation.split())
            dur        = word_count / _TTS_WORDS_PER_SECOND
            end_vid    = start_vid + dur
            start = int(start_vid * fps)
            end   = int(end_vid   * fps)
        else:
            # Default: right-align subtitle to trigger (matches right-aligned audio)
            ts            = event["timestamp"]
            trigger_frame = _find_frame_for_time(timestamps, ts)
            word_count    = len(explanation.split())
            clip_frames   = int((word_count / _TTS_WORDS_PER_SECOND) * fps)
            start = max(0, trigger_frame - clip_frames)
            end   = trigger_frame

        for fi in range(start, end + 1):
            mapping[fi] = explanation
    return mapping


# ---------------------------------------------------------------------------
# Drawing primitives
# ---------------------------------------------------------------------------

def _semi_rect(img: np.ndarray, x1: int, y1: int, x2: int, y2: int, alpha: float) -> None:
    """Draw a filled semi-transparent black rectangle onto img in-place."""
    layer = img.copy()
    cv2.rectangle(layer, (x1, y1), (x2, y2), (0, 0, 0), -1)
    cv2.addWeighted(layer, alpha, img, 1.0 - alpha, 0, img)


def _line_h(scale: float, thickness: int) -> int:
    (_, h), baseline = cv2.getTextSize("Ag", FONT, scale, thickness)
    return h + baseline


# ---------------------------------------------------------------------------
# HUD element renderers
# ---------------------------------------------------------------------------

def _draw_top_bar(frame: np.ndarray, labels: list[str]) -> None:
    """
    Semi-transparent dark strip across the top 8% of the frame.
    Shows detected object labels separated by ' | '.
    Modifies frame in-place.
    """
    h, w = frame.shape[:2]
    bar_h = max(int(h * TOP_BAR_FRAC), 30)

    _semi_rect(frame, 0, 0, w, bar_h, HUD_ALPHA)

    if not labels:
        return

    label_str = "  |  ".join(labels)
    lh = _line_h(TOP_BAR_SCALE, TOP_BAR_THICK)
    (tw, _), _ = cv2.getTextSize(label_str, FONT, TOP_BAR_SCALE, TOP_BAR_THICK)

    text_x = max((w - tw) // 2, EXPL_PAD_X)
    text_y = TOP_BAR_PAD_Y + lh
    cv2.putText(
        frame, label_str, (text_x, text_y),
        FONT, TOP_BAR_SCALE, COLOR_WHITE, TOP_BAR_THICK, cv2.LINE_AA,
    )


def _draw_speed_box(frame: np.ndarray, speed_kmh: float, action_state: str) -> int:
    """
    Compact box in the bottom-left corner showing speed + action state.
    Modifies frame in-place.
    Returns the right edge x-coordinate of the box (for explanation box positioning).
    """
    h, w = frame.shape[:2]
    m = SPEED_BOX_MARGIN
    p = SPEED_BOX_PAD

    speed_str = f"{int(round(speed_kmh))} km/h"
    state_str = action_state

    # Measure text sizes
    (sw, sh), _ = cv2.getTextSize(speed_str, FONT, SPEED_SCALE, SPEED_THICK)
    (aw, ah), _ = cv2.getTextSize(state_str, FONT, STATE_SCALE,  STATE_THICK)

    box_w = max(sw, aw) + p * 2
    box_h = sh + ah + p * 3            # top pad + speed + middle pad + state + bottom pad
    box_x1 = m
    box_x2 = m + box_w
    box_y2 = h - m
    box_y1 = box_y2 - box_h

    _semi_rect(frame, box_x1, box_y1, box_x2, box_y2, HUD_ALPHA)

    # Speed number (large, white)
    cv2.putText(
        frame, speed_str,
        (box_x1 + p, box_y1 + p + sh),
        FONT, SPEED_SCALE, COLOR_WHITE, SPEED_THICK, cv2.LINE_AA,
    )

    # Action state (smaller, colour-coded)
    state_color = _STATE_COLORS.get(action_state, COLOR_WHITE)
    cv2.putText(
        frame, state_str,
        (box_x1 + p, box_y2 - p),
        FONT, STATE_SCALE, state_color, STATE_THICK, cv2.LINE_AA,
    )

    return box_x2


def _draw_explanation(frame: np.ndarray, text: str, x_start: int, idle: bool = False) -> None:
    """
    Semi-transparent box with word-wrapped, centred explanation text.
    Positioned in the bottom 20% of the frame, starting at x_start.
    When idle=True the text is rendered in a dimmed colour.
    Modifies frame in-place.
    """
    if not text:
        return

    lines = []
    for paragraph in text.splitlines():
        lines.extend(textwrap.wrap(paragraph, width=EXPL_WRAP) or [""])
    if not lines:
        return

    h, w = frame.shape[:2]
    lh = _line_h(EXPL_SCALE, EXPL_THICK)

    block_h = lh * len(lines) + EXPL_LINE_GAP * (len(lines) - 1) + EXPL_PAD_Y * 2
    box_x1  = x_start + EXPL_PAD_X
    box_x2  = w - EXPL_PAD_X
    box_w   = box_x2 - box_x1

    area_top = int(h * EXPL_AREA_TOP)
    box_y2   = h - EXPL_PAD_Y // 2
    box_y1   = max(area_top, box_y2 - block_h)

    alpha = HUD_ALPHA * 0.6 if idle else HUD_ALPHA
    _semi_rect(frame, box_x1, box_y1, box_x2, box_y2, alpha)

    text_color = COLOR_DIM_IDLE if idle else COLOR_WHITE
    text_y = box_y1 + EXPL_PAD_Y + lh
    for line in lines:
        (tw, _), _ = cv2.getTextSize(line, FONT, EXPL_SCALE, EXPL_THICK)
        text_x = box_x1 + max((box_w - tw) // 2, 0)   # centre each line
        cv2.putText(
            frame, line, (text_x, text_y),
            FONT, EXPL_SCALE, text_color, EXPL_THICK, cv2.LINE_AA,
        )
        text_y += lh + EXPL_LINE_GAP


def _draw_hud(
    frame:        np.ndarray,
    telemetry:    dict,
    yolo_labels:  list[str],
    explanation:  str,        # kept for API compatibility, unused now
    condition:    str = "",   # kept for API compatibility, unused now
) -> np.ndarray:
    """
    Compose all HUD elements onto a copy of frame and return it.

    Layout (all conditions):
      TOP          — YOLO detected objects
      BOTTOM LEFT  — speedometer + action state
      BOTTOM CENTRE — condition-specific text (see below)

    none:          no bottom text
    template:      always-on latched short action text (passed as explanation)
    descriptive/teleological: GPT-4o text shown only at trigger moments
    """
    out = frame.copy()

    speed_kmh    = telemetry.get("speed_kmh", 0.0)
    action_state = _derive_action_state(telemetry)

    p = SPEED_BOX_PAD
    m = SPEED_BOX_MARGIN
    speed_str = f"{int(round(speed_kmh))} km/h"
    (sw, _), _ = cv2.getTextSize(speed_str, FONT, SPEED_SCALE, SPEED_THICK)
    (aw, _), _ = cv2.getTextSize(action_state, FONT, STATE_SCALE, STATE_THICK)
    box_right = m + max(sw, aw) + p * 2

    # 1. Bottom-centre text — condition-specific
    if condition != "none" and explanation:
        _draw_explanation(out, explanation, box_right, idle=False)

    # 2. Speed / action state box (bottom left)
    _draw_speed_box(out, speed_kmh, action_state)

    # 3. YOLO detected objects (top bar)
    _draw_top_bar(out, yolo_labels)

    return out


# ---------------------------------------------------------------------------
# Single-condition video renderer
# ---------------------------------------------------------------------------

def _render_condition(
    cap:               cv2.VideoCapture,
    out_path:          Path,
    fps:               float,
    frame_size:        tuple[int, int],
    frame_text_map:    dict[int, str],
    telemetry:         list[dict],
    frame_yolo_map:    dict[int, list[str]],
    frame_vehicle_map: dict[int, bool],
    condition:         str,
    total_frames:      int,
) -> None:
    writer = cv2.VideoWriter(str(out_path), FOURCC, fps, frame_size)
    if not writer.isOpened():
        raise RuntimeError(f"VideoWriter could not open: {out_path}")

    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    with tqdm(
        total=total_frames,
        desc=f"  {condition:<14}",
        unit="frame",
        ncols=72,
        leave=True,
    ) as pbar:
        # Latch state for template condition — prevents per-frame flicker
        last_action_text  = ""
        action_text_count = 0
        LATCH_FRAMES      = 8   # frames a new state must hold before switching (~0.27s)

        frame_idx = 0
        while True:
            ret, raw = cap.read()
            if not ret:
                break

            snap        = telemetry[frame_idx] if frame_idx < len(telemetry) else {}
            yolo_lbls   = frame_yolo_map.get(frame_idx, [])
            has_vehicle = frame_vehicle_map.get(frame_idx, False)

            if condition == "template":
                candidate    = _derive_action_text(snap, yolo_lbls, has_vehicle)
                is_emergency = snap.get("brake", 0.0) >= 0.8
                if is_emergency:
                    # Emergency: show immediately, reset latch
                    last_action_text  = candidate
                    action_text_count = 0
                elif candidate != last_action_text:
                    action_text_count += 1
                    if action_text_count >= LATCH_FRAMES:
                        last_action_text  = candidate
                        action_text_count = 0
                else:
                    action_text_count = 0
                expl_text = last_action_text
            else:
                expl_text = frame_text_map.get(frame_idx, "")

            out_frame = _draw_hud(raw, snap, yolo_lbls, expl_text, condition)
            writer.write(out_frame)

            frame_idx += 1
            pbar.update(1)

    writer.release()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_overlays(
    scenario_dir: str | Path,
    conditions:   Optional[list[str]] = None,
) -> dict[str, Path]:
    """
    Generate HUD + explanation overlay videos for the specified conditions.

    Args:
        scenario_dir: Path to recorded scenario folder.
        conditions:   Subset of CONDITIONS to render. Defaults to all 4.

    Returns:
        Dict mapping condition name → output video Path.
    """
    scenario_dir = Path(scenario_dir)
    if not scenario_dir.is_absolute():
        repo_root = Path(__file__).resolve().parents[2]
        scenario_dir = repo_root / scenario_dir

    conditions = conditions or CONDITIONS

    video_path     = scenario_dir / "video.mp4"
    telemetry_path = scenario_dir / "telemetry.json"
    yolo_path      = scenario_dir / "yolo_detections.json"
    exp_dir        = scenario_dir / "explanations"

    for p in (video_path, telemetry_path):
        if not p.exists():
            raise FileNotFoundError(f"{p.name} not found in {scenario_dir}")
    if not exp_dir.exists():
        raise FileNotFoundError(
            f"explanations/ not found in {scenario_dir}. Run generator.py first."
        )

    telemetry          = json.loads(telemetry_path.read_text())
    timestamps         = _build_timestamp_index(telemetry)
    yolo_dets          = json.loads(yolo_path.read_text()) if yolo_path.exists() else []
    frame_yolo_map     = _build_frame_yolo_map(yolo_dets)
    frame_vehicle_map  = _build_frame_vehicle_map(yolo_dets)

    if not yolo_path.exists():
        print("  WARNING: yolo_detections.json not found — top bar will be empty.")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"cv2.VideoCapture could not open: {video_path}")

    fps          = cap.get(cv2.CAP_PROP_FPS)
    frame_width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frame_size   = (frame_width, frame_height)

    print(
        f"\nSource : {video_path.name}  "
        f"({frame_width}×{frame_height}, {fps:.0f} fps, {total_frames} frames)"
    )
    print(f"HUD    : top-bar objects | bottom-left speed+state | bottom-centre explanation")
    print(f"Conditions: {conditions}\n")

    output_paths: dict[str, Path] = {}

    for condition in conditions:
        exp_path = exp_dir / f"{condition}.json"
        if not exp_path.exists():
            print(f"  [SKIP] {condition}: {exp_path.name} not found.")
            continue

        events         = json.loads(exp_path.read_text())
        frame_text_map = _build_frame_text_map(events, timestamps, fps=fps)

        out_path = scenario_dir / f"video_{condition}.mp4"
        _render_condition(
            cap, out_path, fps, frame_size,
            frame_text_map, telemetry, frame_yolo_map, frame_vehicle_map,
            condition, total_frames,
        )

        size_mb       = out_path.stat().st_size / 1e6
        overlay_count = sum(1 for e in events if e.get("explanation"))
        print(f"  → {out_path.name}  ({size_mb:.1f} MB, {overlay_count} overlaid event(s))")
        output_paths[condition] = out_path

    cap.release()
    print(f"\nDone. Videos written to: {scenario_dir}")
    return output_paths


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render HUD + explanation overlays onto AdaptTrust scenario videos."
    )
    parser.add_argument(
        "scenario_dir",
        help="Path to recorded scenario folder (e.g. data/scenarios/recorder_test_run1)",
    )
    parser.add_argument(
        "--conditions",
        nargs="+",
        choices=CONDITIONS,
        default=None,
        help="Which conditions to render (default: all 4).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    try:
        render_overlays(args.scenario_dir, args.conditions)
    except (FileNotFoundError, RuntimeError) as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)
