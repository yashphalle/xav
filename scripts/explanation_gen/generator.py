"""
generator.py — Explanation generation for all 4 AdaptTrust conditions.

Conditions:
  none          Empty string — control condition, no explanation shown.
  template      Rule-based string built from telemetry only (no API call).
  descriptive   GPT-4o factual: "The car is braking because a pedestrian is crossing."
  teleological  GPT-4o intentional: "I'm slowing down to give the pedestrian safe space."

Main entry point:
    from scripts.explanation_gen.generator import generate_all_explanations
    generate_all_explanations("data/scenarios/my_scenario_run1")

Produces:
    data/scenarios/my_scenario_run1/explanations/none.json
    data/scenarios/my_scenario_run1/explanations/template.json
    data/scenarios/my_scenario_run1/explanations/descriptive.json
    data/scenarios/my_scenario_run1/explanations/teleological.json

CLI:
    python scripts/explanation_gen/generator.py data/scenarios/my_scenario_run1
"""

import base64
import json
import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger("generator")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATA_ROOT = _REPO_ROOT / "data"

# ---------------------------------------------------------------------------
# GPT-4o prompts (verbatim from project brief)
# ---------------------------------------------------------------------------

_DESCRIPTIVE_PROMPT = """\
You are an autonomous vehicle assistant. Look at this driving scene.
Vehicle data: Speed={speed} km/h, Brake={brake}, Throttle={throttle}, Steer={steer}
Detected objects: {yolo_objects}
Traffic light: {traffic_light_state}
Describe what the vehicle is doing in 1-2 factual sentences."""

_TELEOLOGICAL_PROMPT = """\
You are an autonomous vehicle explaining actions to your passenger. Speak in first person.
Vehicle data: Speed={speed} km/h, Brake={brake}, Throttle={throttle}, Steer={steer}
Detected objects: {yolo_objects}
Traffic light: {traffic_light_state}
Explain what you are doing and WHY in 1-2 sentences. Focus on intention and goal.
Style: 'I'm slowing down to give the pedestrian ahead safe space to cross.'"""

# ---------------------------------------------------------------------------
# Template rules (no API — trigger_type → human-readable string)
# ---------------------------------------------------------------------------

def _template_explanation(trigger_type: str, snap: dict) -> str:
    """
    Rule-based explanation derived purely from telemetry.
    No API call, always available.
    """
    speed   = round(snap.get("speed_kmh", 0), 1)
    brake   = round(snap.get("brake", 0), 2)
    throttle= round(snap.get("throttle", 0), 2)
    steer   = round(snap.get("steer", 0), 2)
    gear    = snap.get("gear", 1)

    rules = {
        "BRAKING": (
            f"The vehicle is braking (brake={brake}) from {speed} km/h. "
            "Decelerating due to an obstacle or traffic condition ahead."
        ),
        "ACCELERATING": (
            f"The vehicle is accelerating (throttle={throttle}) to {speed} km/h in gear {gear}. "
            "Increasing speed to match traffic flow."
        ),
        "LANE_CHANGE": (
            f"The vehicle is changing lanes (steer={steer:+.2f}) at {speed} km/h. "
            "Adjusting lateral position on the road."
        ),
        "TURNING": (
            f"The vehicle is turning (steer={steer:+.2f}) at {speed} km/h. "
            "Following the road curvature."
        ),
        "SPEED_CHANGE": (
            f"The vehicle speed changed significantly to {speed} km/h "
            f"(throttle={throttle}, brake={brake})."
        ),
        "PEDESTRIAN_CLOSE": (
            f"A pedestrian is detected close to the vehicle. "
            f"Current speed {speed} km/h, brake={brake}."
        ),
        "COLLISION_RISK": (
            f"Collision risk detected. Emergency response active at {speed} km/h "
            f"(brake={brake})."
        ),
    }
    return rules.get(
        trigger_type,
        f"Vehicle action detected: {trigger_type} at {speed} km/h.",
    )


# ---------------------------------------------------------------------------
# GPT-4o call
# ---------------------------------------------------------------------------

_PLACEHOLDER = "[GPT-4o explanation unavailable — API key not configured or no credits]"
_MIN_CALL_INTERVAL = 3.0   # seconds between API calls
_MAX_RETRIES = 3

_last_call_time: float = 0.0  # module-level for rate limiting across calls


def _get_openai_client():
    """
    Lazily import openai and return a configured client.
    Returns None if the key is absent or is the placeholder value.
    """
    load_dotenv(_REPO_ROOT / ".env")
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or api_key == "your_key_here":
        return None
    try:
        from openai import OpenAI
        return OpenAI(api_key=api_key)
    except Exception as e:
        logger.warning("Could not initialise OpenAI client: %s", e)
        return None


def _encode_image(image_path: Path) -> str:
    """Return base64-encoded JPEG string."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _build_context(snap: dict, yolo_detections: list[dict], timestamp: float) -> dict:
    """
    Extract human-readable context fields for prompt formatting.

    Args:
        snap:            Telemetry snapshot from the action event.
        yolo_detections: Full yolo_detections.json list (all frames).
        timestamp:       Event timestamp (sim seconds).

    Returns dict with keys: speed, brake, throttle, steer, yolo_objects, traffic_light_state.
    """
    # Find YOLO detections within ±0.5 s of the trigger frame
    nearby = [
        d for d in yolo_detections
        if abs(d.get("timestamp", 0) - timestamp) <= 0.5
    ]

    # Summarise object classes (deduplicated, sorted by confidence)
    seen: dict[str, float] = {}
    for d in nearby:
        cls = d["class_name"]
        conf = d.get("confidence", 0)
        if conf > seen.get(cls, 0):
            seen[cls] = conf

    if seen:
        yolo_str = ", ".join(
            f"{cls} ({conf:.0%})" for cls, conf in sorted(seen.items(), key=lambda x: -x[1])
        )
    else:
        yolo_str = "none detected"

    tl_state = "detected" if "traffic light" in seen else "not detected"

    return {
        "speed":               round(snap.get("speed_kmh", 0), 1),
        "brake":               round(snap.get("brake", 0), 2),
        "throttle":            round(snap.get("throttle", 0), 2),
        "steer":               round(snap.get("steer", 0), 2),
        "yolo_objects":        yolo_str,
        "traffic_light_state": tl_state,
    }


def _call_gpt4o(
    client,
    prompt_template: str,
    context: dict,
    image_path: Path | None,
) -> str:
    """
    Make one GPT-4o API call with rate limiting and 429 retry.

    Returns the explanation string, or _PLACEHOLDER on any unrecoverable error.
    """
    global _last_call_time

    prompt = prompt_template.format(**context)
    messages: list[dict] = []

    if image_path and image_path.exists():
        b64 = _encode_image(image_path)
        messages.append({
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{b64}",
                        "detail": "low",   # ~$0.00085/image vs $0.00340 for high
                    },
                },
                {"type": "text", "text": prompt},
            ],
        })
    else:
        logger.warning("Trigger frame not found at %s — sending text-only prompt.", image_path)
        messages.append({"role": "user", "content": prompt})

    for attempt in range(1, _MAX_RETRIES + 1):
        # Rate limit
        gap = time.monotonic() - _last_call_time
        if gap < _MIN_CALL_INTERVAL:
            time.sleep(_MIN_CALL_INTERVAL - gap)

        try:
            _last_call_time = time.monotonic()
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                max_tokens=120,
                temperature=0.3,
            )
            return response.choices[0].message.content.strip()

        except Exception as e:
            err_str = str(e)

            # 429 — rate limited by OpenAI; back off and retry
            if "429" in err_str or "rate_limit" in err_str.lower():
                wait = 10 * attempt
                logger.warning("Rate limited (attempt %d/%d). Waiting %ds …", attempt, _MAX_RETRIES, wait)
                time.sleep(wait)
                continue

            # Quota / billing errors — no point retrying
            if any(k in err_str.lower() for k in ("quota", "billing", "insufficient_quota", "401", "authentication")):
                logger.warning("API quota/auth error — skipping remaining GPT-4o calls: %s", e)
                raise _SkipGPT(str(e)) from e

            # Any other error on last attempt
            if attempt == _MAX_RETRIES:
                logger.error("GPT-4o call failed after %d attempts: %s", _MAX_RETRIES, e)
                return _PLACEHOLDER

            logger.warning("GPT-4o error (attempt %d/%d): %s", attempt, _MAX_RETRIES, e)
            time.sleep(2 * attempt)

    return _PLACEHOLDER


class _SkipGPT(Exception):
    """Raised when further GPT calls should be skipped (quota/auth)."""


# ---------------------------------------------------------------------------
# Per-event explanation builders
# ---------------------------------------------------------------------------

def _make_entry(event: dict, explanation: str) -> dict:
    return {
        "event_index":  event.get("event_index", 0),
        "trigger_type": event["trigger_type"],
        "timestamp":    event["timestamp"],
        "explanation":  explanation,
    }


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def generate_all_explanations(scenario_dir: str | Path) -> dict[str, Path]:
    """
    Generate all 4 explanation condition JSON files for a recorded scenario.

    Args:
        scenario_dir: Path to a recorded scenario folder, e.g.
                      'data/scenarios/L1_highway_cruise_run1'
                      Accepts both absolute and relative-to-repo-root paths.

    Returns:
        Dict mapping condition name → output Path for each of the 4 files.
    """
    scenario_dir = Path(scenario_dir)
    if not scenario_dir.is_absolute():
        scenario_dir = _REPO_ROOT / scenario_dir

    events_path = scenario_dir / "action_events.json"
    yolo_path   = scenario_dir / "yolo_detections.json"
    exp_dir     = scenario_dir / "explanations"

    if not events_path.exists():
        raise FileNotFoundError(f"action_events.json not found in {scenario_dir}")

    exp_dir.mkdir(exist_ok=True)

    events: list[dict] = json.loads(events_path.read_text())
    # Stamp event_index for stable cross-condition alignment
    for i, ev in enumerate(events):
        ev["event_index"] = i

    yolo_detections: list[dict] = (
        json.loads(yolo_path.read_text()) if yolo_path.exists() else []
    )

    logger.info(
        "Generating explanations for %d events in %s",
        len(events), scenario_dir.name,
    )

    # ------------------------------------------------------------------
    # Condition 1 — None (control)
    # ------------------------------------------------------------------
    none_entries = [_make_entry(ev, "") for ev in events]

    # ------------------------------------------------------------------
    # Condition 2 — Template (always succeeds)
    # ------------------------------------------------------------------
    template_entries = [
        _make_entry(ev, _template_explanation(ev["trigger_type"], ev["telemetry_snapshot"]))
        for ev in events
    ]

    # ------------------------------------------------------------------
    # Conditions 3 & 4 — GPT-4o (descriptive + teleological)
    # ------------------------------------------------------------------
    client = _get_openai_client()
    gpt_available = client is not None

    if not gpt_available:
        logger.warning(
            "OPENAI_API_KEY not set or is placeholder — "
            "saving placeholder text for descriptive and teleological conditions."
        )

    descriptive_entries  = []
    teleological_entries = []
    gpt_skipped = False

    for ev in events:
        snap      = ev["telemetry_snapshot"]
        trigger   = ev["trigger_type"]
        ts        = ev["timestamp"]
        ctx       = _build_context(snap, yolo_detections, ts)

        # Resolve trigger frame path (stored relative to data/)
        raw_frame_path = ev.get("frame_path")
        image_path: Path | None = None
        if raw_frame_path:
            candidate = _DATA_ROOT / raw_frame_path
            image_path = candidate if candidate.exists() else None
            if not candidate.exists():
                logger.warning("Trigger frame not found: %s", candidate)

        logger.info("  Event %d: %s @ t=%.2fs", ev["event_index"], trigger, ts)

        if gpt_available and not gpt_skipped:
            try:
                desc = _call_gpt4o(client, _DESCRIPTIVE_PROMPT, ctx, image_path)
                tele = _call_gpt4o(client, _TELEOLOGICAL_PROMPT, ctx, image_path)
            except _SkipGPT as e:
                logger.warning("GPT-4o disabled for remainder of run: %s", e)
                gpt_skipped = True
                desc = _PLACEHOLDER
                tele = _PLACEHOLDER
        else:
            desc = _PLACEHOLDER
            tele = _PLACEHOLDER

        descriptive_entries.append(_make_entry(ev, desc))
        teleological_entries.append(_make_entry(ev, tele))

    # ------------------------------------------------------------------
    # Write output files
    # ------------------------------------------------------------------
    outputs: dict[str, Path] = {}
    for name, entries in [
        ("none",         none_entries),
        ("template",     template_entries),
        ("descriptive",  descriptive_entries),
        ("teleological", teleological_entries),
    ]:
        path = exp_dir / f"{name}.json"
        with open(path, "w") as f:
            json.dump(entries, f, indent=2)
        outputs[name] = path
        logger.info("  Saved %s (%d entries)", path.name, len(entries))

    logger.info("Done — explanations written to %s", exp_dir)
    return outputs


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if len(sys.argv) < 2:
        print(f"Usage: python {Path(__file__).name} <scenario_dir>")
        print(f"Example: python {Path(__file__).name} data/scenarios/recorder_test_run1")
        sys.exit(1)

    outputs = generate_all_explanations(sys.argv[1])

    print("\nGenerated explanation files:")
    for condition, path in outputs.items():
        entries = json.loads(path.read_text())
        sample  = entries[0]["explanation"][:80] + "…" if entries and entries[0]["explanation"] else "(empty)"
        print(f"  {condition:<14} {path.name}  — sample: \"{sample}\"")
