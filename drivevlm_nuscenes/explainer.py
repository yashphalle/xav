"""
GPT-4o Vision API calls and prompt logic.
"""

import time
from typing import Any

from openai import OpenAI

from config import OPENAI_MODEL
from can_loader import summarize_window_telemetry
from utils import encode_image_base64


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_DESCRIPTIVE = (
    "You are an autonomous vehicle perception and action logging system. "
    "You will be shown a sequence of frames from the front camera of a self-driving "
    "vehicle. Describe what the vehicle did during this sequence in one to two "
    "concise sentences. Focus on observable actions: speed changes, steering, "
    "reactions to road users or signals. Do not infer intent. Begin with \"The vehicle\"."
)

SYSTEM_PROMPT_TELEOLOGICAL = (
    "You are an autonomous vehicle speaking directly to its passenger in first person. "
    "You will be shown a sequence of frames from your own front camera. "
    "In one to two concise sentences, explain in first person WHY you took the action "
    "shown — your goals, what risk you were avoiding, or your safety priority. "
    "Use natural spoken language. Begin with \"I am going to\", \"I will\", or \"I am slowing down\"."
)


# ---------------------------------------------------------------------------
# Message construction
# ---------------------------------------------------------------------------

def build_user_message(window_frames: list[dict], telemetry_summary: dict) -> list[dict]:
    """
    Build the OpenAI API content block list for a window of frames.

    Layout:
        1. Text block — telemetry context
        2. One image_url block per frame (base64 JPEG data URI)
        3. Text block — final instruction
    """
    n = len(window_frames)
    avg_speed = telemetry_summary.get("avg_speed_kmh", 0.0)
    braking = telemetry_summary.get("braking_detected", False)
    trend = telemetry_summary.get("speed_trend", "steady")

    content: list[dict] = [
        {
            "type": "text",
            "text": (
                f"Here are {n} consecutive front camera frames from a driving sequence. "
                f"Ego vehicle speed: {avg_speed} km/h, "
                f"braking detected: {braking}, "
                f"speed trend: {trend}."
            ),
        }
    ]

    for frame in window_frames:
        b64 = encode_image_base64(frame["frame_path"])
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{b64}",
                    "detail": "low",  # use "high" for better accuracy at higher cost
                },
            }
        )

    content.append(
        {
            "type": "text",
            "text": "Based on these frames and telemetry, provide your explanation now.",
        }
    )

    return content


# ---------------------------------------------------------------------------
# Single-window explanation
# ---------------------------------------------------------------------------

def generate_explanation(
    client: OpenAI,
    window_frames: list[dict],
    telemetry_summary: dict,
    explanation_type: str,
) -> str:
    """
    Call the GPT-4o Vision API for one window and return the explanation text.

    `explanation_type` must be "descriptive" or "teleological".
    """
    if explanation_type == "descriptive":
        system_prompt = SYSTEM_PROMPT_DESCRIPTIVE
    elif explanation_type == "teleological":
        system_prompt = SYSTEM_PROMPT_TELEOLOGICAL
    else:
        raise ValueError(f"Unknown explanation_type: '{explanation_type}'")

    user_content = build_user_message(window_frames, telemetry_summary)

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        max_tokens=150,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    )

    return response.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# Full-scene explanations
# ---------------------------------------------------------------------------

def generate_all_explanations(
    client: OpenAI,
    windows: list[list[dict]],
    can_data: list[dict],
    scene_name: str,
    nusc_can: Any,
) -> list[dict]:
    """
    Generate descriptive and teleological explanations for every window in
    the scene.

    Returns a list of dicts (one per window):
        {
            "window_index": int,
            "descriptive":  str,
            "teleological": str,
            "telemetry":    dict,
        }

    Sleeps 0.5 s between windows to stay within API rate limits.
    """
    results: list[dict] = []
    total = len(windows)

    for i, window in enumerate(windows):
        print(f"Window {i + 1}/{total}: generating explanations...")

        telemetry = summarize_window_telemetry(can_data, window)

        descriptive = generate_explanation(client, window, telemetry, "descriptive")
        teleological = generate_explanation(client, window, telemetry, "teleological")

        results.append(
            {
                "window_index": i,
                "descriptive": descriptive,
                "teleological": teleological,
                "telemetry": telemetry,
            }
        )

        if i < total - 1:
            time.sleep(0.5)

    return results
