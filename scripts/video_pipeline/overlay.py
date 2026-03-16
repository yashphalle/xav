"""
overlay.py — Render explanation overlays onto recorded scenario videos.

For each of the 4 explanation conditions, reads the corresponding JSON file
and produces a new video with the explanation text overlaid starting 2 sim-
seconds before each action trigger.

Output files (written alongside the input video):
    video_none.mp4
    video_template.mp4
    video_descriptive.mp4
    video_teleological.mp4

Usage:
    python scripts/video_pipeline/overlay.py data/scenarios/recorder_test_run1
    python scripts/video_pipeline/overlay.py data/scenarios/recorder_test_run1 --conditions template descriptive
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

FONT            = cv2.FONT_HERSHEY_SIMPLEX
FONT_SCALE      = 0.8
FONT_THICKNESS  = 2
FONT_COLOR      = (255, 255, 255)   # white
BOX_ALPHA       = 0.55              # opacity of black background box
BOX_MARGIN_X    = 20                # px padding inside box, horizontal
BOX_MARGIN_Y    = 12                # px padding inside box, vertical
LINE_SPACING    = 8                 # extra px between text lines
WRAP_WIDTH      = 80                # chars per line before word-wrap
TEXT_AREA_TOP   = 0.80              # overlay starts at 80% frame height

# How long (sim-seconds) to display each explanation
DISPLAY_BEFORE_S = 2.0   # show this many seconds before the trigger
DISPLAY_AFTER_S  = 3.0   # keep showing this many seconds after the trigger

# Output codec  (mp4v = MPEG-4 Part 2; reliable cross-platform for OpenCV)
FOURCC = cv2.VideoWriter_fourcc(*"mp4v")

CONDITIONS = ["none", "template", "descriptive", "teleological"]


# ---------------------------------------------------------------------------
# Text rendering helpers
# ---------------------------------------------------------------------------

def _wrap_text(text: str, width: int = WRAP_WIDTH) -> list[str]:
    """Wrap text at `width` characters, preserving newlines."""
    if not text:
        return []
    lines = []
    for paragraph in text.splitlines():
        lines.extend(textwrap.wrap(paragraph, width=width) or [""])
    return lines


def _line_height(scale: float = FONT_SCALE, thickness: int = FONT_THICKNESS) -> int:
    """Return pixel height of one text line (ascender + descender)."""
    (_, h), baseline = cv2.getTextSize("Ag", FONT, scale, thickness)
    return h + baseline


def _draw_overlay(frame: np.ndarray, text: str) -> np.ndarray:
    """
    Draw a semi-transparent black box with wrapped white text in the bottom
    20% of `frame`.  Returns a new frame (original is not modified).
    """
    if not text:
        return frame

    lines = _wrap_text(text)
    if not lines:
        return frame

    h, w = frame.shape[:2]
    lh = _line_height()
    block_h = lh * len(lines) + LINE_SPACING * (len(lines) - 1) + BOX_MARGIN_Y * 2
    block_w = w - BOX_MARGIN_X * 2

    # Clamp box to bottom TEXT_AREA_TOP–100% band
    area_top = int(h * TEXT_AREA_TOP)
    box_y1 = max(area_top, h - block_h - BOX_MARGIN_Y)
    box_y2 = h - BOX_MARGIN_Y // 2
    box_x1 = BOX_MARGIN_X
    box_x2 = w - BOX_MARGIN_X

    # Semi-transparent black background
    out = frame.copy()
    overlay_layer = out.copy()
    cv2.rectangle(overlay_layer, (box_x1, box_y1), (box_x2, box_y2), (0, 0, 0), -1)
    cv2.addWeighted(overlay_layer, BOX_ALPHA, out, 1.0 - BOX_ALPHA, 0, out)

    # Text lines
    text_x = box_x1 + BOX_MARGIN_X
    text_y = box_y1 + BOX_MARGIN_Y + lh
    for line in lines:
        cv2.putText(out, line, (text_x, text_y), FONT, FONT_SCALE, FONT_COLOR, FONT_THICKNESS, cv2.LINE_AA)
        text_y += lh + LINE_SPACING

    return out


# ---------------------------------------------------------------------------
# Frame-index ↔ sim-time mapping
# ---------------------------------------------------------------------------

def _build_timestamp_index(telemetry: list[dict]) -> list[float]:
    """Return a list where index i → sim timestamp of frame i."""
    return [entry["timestamp"] for entry in telemetry]


def _find_frame_for_time(timestamps: list[float], sim_time: float) -> int:
    """
    Binary-search for the frame index whose timestamp is closest to sim_time.
    Clamps to [0, len-1].
    """
    lo, hi = 0, len(timestamps) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if timestamps[mid] < sim_time:
            lo = mid + 1
        else:
            hi = mid
    return max(0, min(lo, len(timestamps) - 1))


def _build_frame_text_map(
    events: list[dict],
    timestamps: list[float],
    before_s: float = DISPLAY_BEFORE_S,
    after_s: float = DISPLAY_AFTER_S,
) -> dict[int, str]:
    """
    Returns a dict mapping frame_index → explanation text for every frame that
    should show an overlay.  Later events overwrite earlier ones if they overlap
    (shouldn't happen given the 3 s cooldown, but handled safely).
    """
    mapping: dict[int, str] = {}
    for event in events:
        explanation = event.get("explanation", "")
        if not explanation:
            continue
        ts = event["timestamp"]
        start_frame = _find_frame_for_time(timestamps, ts - before_s)
        end_frame   = _find_frame_for_time(timestamps, ts + after_s)
        for fi in range(start_frame, end_frame + 1):
            mapping[fi] = explanation
    return mapping


# ---------------------------------------------------------------------------
# Single-condition video renderer
# ---------------------------------------------------------------------------

def _render_condition(
    cap: cv2.VideoCapture,
    out_path: Path,
    fps: float,
    frame_size: tuple[int, int],
    frame_text_map: dict[int, str],
    condition: str,
    total_frames: int,
) -> None:
    """
    Read all frames from `cap` (rewound to frame 0) and write overlay video.
    """
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
        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            text = frame_text_map.get(frame_idx, "")
            out_frame = _draw_overlay(frame, text)
            writer.write(out_frame)

            frame_idx += 1
            pbar.update(1)

    writer.release()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def render_overlays(
    scenario_dir: str | Path,
    conditions: Optional[list[str]] = None,
) -> dict[str, Path]:
    """
    Generate overlay videos for the specified conditions.

    Args:
        scenario_dir: Path to a recorded scenario folder.
        conditions:   Subset of CONDITIONS to render.  Defaults to all 4.

    Returns:
        Dict mapping condition name → output video Path.
    """
    scenario_dir = Path(scenario_dir)
    if not scenario_dir.is_absolute():
        repo_root = Path(__file__).resolve().parents[2]
        scenario_dir = repo_root / scenario_dir

    conditions = conditions or CONDITIONS

    video_path    = scenario_dir / "video.mp4"
    telemetry_path = scenario_dir / "telemetry.json"
    exp_dir       = scenario_dir / "explanations"

    if not video_path.exists():
        raise FileNotFoundError(f"video.mp4 not found in {scenario_dir}")
    if not telemetry_path.exists():
        raise FileNotFoundError(f"telemetry.json not found in {scenario_dir}")
    if not exp_dir.exists():
        raise FileNotFoundError(
            f"explanations/ not found in {scenario_dir}. "
            "Run generator.py first."
        )

    # Load telemetry for frame↔time mapping
    telemetry = json.loads(telemetry_path.read_text())
    timestamps = _build_timestamp_index(telemetry)

    # Open source video
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"cv2.VideoCapture could not open: {video_path}")

    fps          = cap.get(cv2.CAP_PROP_FPS)
    frame_width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frame_size   = (frame_width, frame_height)

    print(
        f"\nSource: {video_path.name}  "
        f"({frame_width}×{frame_height}, {fps:.0f} fps, {total_frames} frames)"
    )
    print(f"Conditions: {conditions}\n")

    output_paths: dict[str, Path] = {}

    for condition in conditions:
        exp_path = exp_dir / f"{condition}.json"
        if not exp_path.exists():
            print(f"  [SKIP] {condition}: {exp_path.name} not found.")
            continue

        events = json.loads(exp_path.read_text())
        frame_text_map = _build_frame_text_map(events, timestamps)

        out_path = scenario_dir / f"video_{condition}.mp4"
        _render_condition(cap, out_path, fps, frame_size, frame_text_map, condition, total_frames)

        size_mb = out_path.stat().st_size / 1e6
        overlay_count = sum(1 for e in events if e.get("explanation"))
        print(
            f"  → {out_path.name}  "
            f"({size_mb:.1f} MB, {overlay_count} overlaid event(s))"
        )
        output_paths[condition] = out_path

    cap.release()
    print(f"\nDone. Videos written to: {scenario_dir}")
    return output_paths


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render explanation overlays onto AdaptTrust scenario videos."
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
