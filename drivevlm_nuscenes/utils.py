"""
Shared helpers: image encoding, text wrapping, and OpenCV text overlay.
"""

import base64
import cv2
import numpy as np
from PIL import Image
import io

from config import MAX_LINE_WIDTH_CHARS, MAX_TEXT_LINES


def encode_image_base64(image_path: str) -> str:
    """
    Read an image, resize it to 800x450 to reduce API payload, and return
    the base64-encoded JPEG string.

    nuScenes CAM_FRONT images are 1600x900 — halving keeps aspect ratio and
    cuts payload by ~75%.
    """
    img = Image.open(image_path).convert("RGB")
    img = img.resize((800, 450), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


def wrap_text(text: str, max_chars_per_line: int = MAX_LINE_WIDTH_CHARS) -> list[str]:
    """
    Greedy word-wrap. Returns a list of line strings.
    Truncates to MAX_TEXT_LINES and appends '...' if necessary.
    """
    words = text.split()
    lines: list[str] = []
    current = ""

    for word in words:
        candidate = f"{current} {word}".strip() if current else word
        if len(candidate) <= max_chars_per_line:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)

    if len(lines) > MAX_TEXT_LINES:
        lines = lines[:MAX_TEXT_LINES]
        # truncate last line and add ellipsis
        last = lines[-1]
        if len(last) > max_chars_per_line - 3:
            last = last[: max_chars_per_line - 3]
        lines[-1] = last + "..."

    return lines


def draw_text_overlay(
    frame_bgr: np.ndarray,
    text_lines: list[str],
    color: tuple[int, int, int],
    font_scale: float,
    thickness: int,
    alpha: float,
) -> np.ndarray:
    """
    Burn text lines onto a copy of frame_bgr at the bottom of the image.

    Draws a semi-transparent dark rectangle behind the text block, then
    renders each line with cv2.putText.

    Returns the modified frame (the original is not mutated).
    """
    frame = frame_bgr.copy()
    font = cv2.FONT_HERSHEY_SIMPLEX
    line_spacing = 6
    pad_x = 15
    pad_y = 20

    # Measure text block dimensions
    line_heights = []
    line_widths = []
    for line in text_lines:
        (w, h), baseline = cv2.getTextSize(line, font, font_scale, thickness)
        line_heights.append(h + baseline)
        line_widths.append(w)

    block_w = max(line_widths) + pad_x * 2
    block_h = sum(line_heights) + line_spacing * (len(text_lines) - 1) + pad_y * 2

    frame_h, frame_w = frame.shape[:2]
    x0 = pad_x
    y0 = frame_h - block_h - pad_y
    x1 = x0 + block_w
    y1 = y0 + block_h

    # Clamp to frame boundaries
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(frame_w, x1), min(frame_h, y1)

    # Semi-transparent dark background
    overlay = frame.copy()
    cv2.rectangle(overlay, (x0, y0), (x1, y1), (0, 0, 0), cv2.FILLED)
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)

    # Draw each line
    cursor_y = y0 + pad_y
    for line, lh in zip(text_lines, line_heights):
        cursor_y += lh
        cv2.putText(frame, line, (x0 + pad_x, cursor_y), font, font_scale, color, thickness, cv2.LINE_AA)
        cursor_y += line_spacing

    return frame


def draw_label(
    frame_bgr: np.ndarray,
    label: str,
    color: tuple[int, int, int],
    font_scale: float = 0.5,
    thickness: int = 1,
) -> np.ndarray:
    """Draw a small label string in the top-left corner of the frame."""
    frame = frame_bgr.copy()
    font = cv2.FONT_HERSHEY_SIMPLEX
    (w, h), _ = cv2.getTextSize(label, font, font_scale, thickness)
    cv2.rectangle(frame, (8, 8), (w + 20, h + 20), (0, 0, 0), cv2.FILLED)
    cv2.putText(frame, label, (14, h + 14), font, font_scale, color, thickness, cv2.LINE_AA)
    return frame


def draw_speed(
    frame_bgr: np.ndarray,
    speed_kmh: float,
    font_scale: float = 0.5,
    thickness: int = 1,
) -> np.ndarray:
    """Draw ego speed in the top-right corner of the frame."""
    frame = frame_bgr.copy()
    font = cv2.FONT_HERSHEY_SIMPLEX
    text = f"{speed_kmh:.1f} km/h"
    (w, h), _ = cv2.getTextSize(text, font, font_scale, thickness)
    frame_w = frame.shape[1]
    x = frame_w - w - 20
    cv2.rectangle(frame, (x - 8, 8), (frame_w - 8, h + 20), (0, 0, 0), cv2.FILLED)
    cv2.putText(frame, text, (x, h + 14), font, font_scale, (200, 255, 200), thickness, cv2.LINE_AA)
    return frame
