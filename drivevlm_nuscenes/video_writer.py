"""
Frame-to-video rendering with explanation text overlay.
"""

import os

import cv2

from config import (
    FPS_OUTPUT,
    FONT_SCALE,
    FONT_THICKNESS,
    TEXT_COLOR_DESCRIPTIVE,
    TEXT_COLOR_TELEOLOGICAL,
    MAX_LINE_WIDTH_CHARS,
    OUTPUT_DIR,
)
from utils import draw_text_overlay, draw_label, draw_speed, wrap_text

# Label colours for the corner badge
_LABEL_COLOR_DESCRIPTIVE = (255, 255, 255)   # white
_LABEL_COLOR_TELEOLOGICAL = (100, 220, 255)  # light blue


def write_explanation_video(
    frames: list[dict],
    explanations: list[dict],
    frame_to_window_map: dict[int, int],
    output_path: str,
    explanation_type: str,
    fps: int = FPS_OUTPUT,
) -> None:
    """
    Render an MP4 video where every frame has:
      - explanation text burned at the bottom
      - a DESCRIPTIVE / TELEOLOGICAL badge in the top-left corner
      - ego speed in the top-right corner

    `explanation_type` must be "descriptive" or "teleological".

    NOTE: If the output file is 0 bytes, try codec "avc1" instead of "mp4v".
    """
    if explanation_type == "descriptive":
        text_color = TEXT_COLOR_DESCRIPTIVE
        label_color = _LABEL_COLOR_DESCRIPTIVE
        label_text = "DESCRIPTIVE"
    else:
        text_color = TEXT_COLOR_TELEOLOGICAL
        label_color = _LABEL_COLOR_TELEOLOGICAL
        label_text = "TELEOLOGICAL"

    # Determine frame size from first image
    first_frame = cv2.imread(frames[0]["frame_path"])
    if first_frame is None:
        raise FileNotFoundError(f"Cannot read frame: {frames[0]['frame_path']}")
    h, w = first_frame.shape[:2]

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(output_path, fourcc, fps, (w, h))

    for frame_idx, frame_info in enumerate(frames):
        img = cv2.imread(frame_info["frame_path"])
        if img is None:
            print(f"  Warning: skipping unreadable frame {frame_info['frame_path']}")
            continue

        window_idx = frame_to_window_map[frame_idx]
        exp_record = explanations[window_idx]

        explanation_text = exp_record[explanation_type]
        telemetry = exp_record["telemetry"]
        speed = telemetry.get("avg_speed_kmh", 0.0)

        # Bottom text overlay
        text_lines = wrap_text(explanation_text, MAX_LINE_WIDTH_CHARS)
        img = draw_text_overlay(img, text_lines, text_color, FONT_SCALE, FONT_THICKNESS, alpha=0.55)

        # Top-left badge
        img = draw_label(img, label_text, label_color)

        # Top-right speed
        img = draw_speed(img, speed)

        writer.write(img)

    writer.release()
    print(f"  Written: {output_path}")


def write_both_videos(
    frames: list[dict],
    explanations: list[dict],
    frame_to_window_map: dict[int, int],
    output_dir: str = OUTPUT_DIR,
    fps: int = FPS_OUTPUT,
) -> None:
    """Write descriptive.mp4 and teleological.mp4 into output_dir, with TTS voice."""
    from audio_writer import add_voice_to_video

    os.makedirs(output_dir, exist_ok=True)

    descriptive_path  = os.path.join(output_dir, "descriptive.mp4")
    teleological_path = os.path.join(output_dir, "teleological.mp4")
    total_frames      = len(frames)

    print("\nRendering descriptive video...")
    write_explanation_video(
        frames, explanations, frame_to_window_map,
        descriptive_path, "descriptive", fps,
    )
    add_voice_to_video(
        descriptive_path, explanations, frame_to_window_map,
        total_frames, "descriptive", fps,
    )

    print("\nRendering teleological video...")
    write_explanation_video(
        frames, explanations, frame_to_window_map,
        teleological_path, "teleological", fps,
    )
    add_voice_to_video(
        teleological_path, explanations, frame_to_window_map,
        total_frames, "teleological", fps,
    )

    print(f"\nOutput files:")
    print(f"  {os.path.abspath(descriptive_path)}")
    print(f"  {os.path.abspath(teleological_path)}")
