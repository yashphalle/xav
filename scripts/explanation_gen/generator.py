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
You are an autonomous vehicle assistant. Look at these frames — an action is about to happen.
Vehicle data: Speed={speed} km/h, Brake={brake}, Throttle={throttle}, Steer={steer}
Detected objects: {yolo_objects}
Traffic light: {traffic_light_state}
Nearest participant: {nearest_npc}
In exactly 1 sentence of 10 words or fewer, describe what the vehicle is about to do and why. \
Use anticipatory language (e.g. "is slowing down", "is preparing to stop", "is moving to the side"). \
Example: 'The vehicle is slowing down for a pedestrian ahead.'"""

_TELEOLOGICAL_PROMPT = """\
You are an autonomous vehicle speaking directly to your passenger. Look at these frames — you are about to take an action.
Vehicle data: Speed={speed} km/h, Brake={brake}, Throttle={throttle}, Steer={steer}
Detected objects: {yolo_objects}
Traffic light: {traffic_light_state}
Nearest participant: {nearest_npc}
In exactly 1 short sentence, tell the passenger what you are about to do and why. \
Use first person anticipatory language (e.g. "I'm slowing down to...", "I'm pulling over because..."). \
Example: 'I'm slowing down to give the pedestrian ahead safe space to cross.'"""

# ---------------------------------------------------------------------------
# Template rules (no API — trigger_type → human-readable string)
# ---------------------------------------------------------------------------

def _template_explanation(
    trigger_type: str,
    snap: dict,
    yolo_nearby: list[str] | None = None,
) -> str:
    """
    Terse, mechanical rule-based explanation — mirrors early BDD-X style.
    Maximum ~6 words: action verb + primary cause only.

    Priority for each trigger type is context-first: what CARLA/YOLO actually
    observed takes precedence over generic fallbacks.

    Args:
        trigger_type: Trigger type string from action_events.json.
        snap:         Telemetry snapshot including traffic_light_state.
        yolo_nearby:  YOLO class names detected within ±0.5 s of the trigger.
    """
    nearby    = set(yolo_nearby or [])
    steer     = snap.get("steer", 0.0)
    tl_state  = snap.get("traffic_light_state", "none")   # "red"|"yellow"|"green"|"none"
    speed_kmh = snap.get("speed_kmh", 0.0)

    has_pedestrian    = "person"        in nearby
    has_cyclist       = "bicycle"       in nearby
    # YOLO traffic light detection — used as fallback when traffic_light_state
    # is absent (recordings made before scenario_base added the field).
    # If the vehicle is braking and YOLO sees a traffic light, it is red.
    has_yolo_tl       = "traffic light" in nearby

    # ------------------------------------------------------------------
    # BRAKING — ordered by specificity of observed cause.
    # Emergency brakes (brake >= 0.8) use urgent language.
    # ------------------------------------------------------------------
    if trigger_type == "BRAKING":
        brake_val    = snap.get("brake", 0.0)
        is_emergency = brake_val >= 0.8
        prefix       = "Emergency brake!" if is_emergency else "Braking."

        # Pedestrian/cyclist take highest priority
        if has_pedestrian:
            return f"{prefix} Pedestrian ahead."
        if has_cyclist:
            return f"{prefix} Cyclist ahead."
        # Vehicle in frame during emergency = cut-in or obstacle
        has_vehicle = any(c in (yolo_nearby or []) for c in ("car", "truck", "bus", "motorcycle"))
        if is_emergency and has_vehicle:
            return "Emergency brake! Vehicle ahead."
        if tl_state == "yellow":
            return "Braking. Yellow light."
        if tl_state == "red" or has_yolo_tl:
            return f"{prefix} Red light."
        return f"{prefix} Obstacle ahead." if is_emergency else "Braking. Obstacle ahead."

    # ------------------------------------------------------------------
    # ACCELERATING
    # ------------------------------------------------------------------
    if trigger_type == "ACCELERATING":
        if tl_state == "green":
            return "Accelerating. Green light."
        if has_yolo_tl:                   # vehicle departed from a traffic light
            return "Accelerating. Green light."
        # If speed is low at trigger time, vehicle was recently stopped
        if speed_kmh < 15:
            return "Resuming. Road is clear."
        return "Accelerating."

    # ------------------------------------------------------------------
    # LANE_CHANGE / TURNING — direction from steer sign
    # ------------------------------------------------------------------
    if trigger_type in ("LANE_CHANGE", "TURNING"):
        return "Turning right." if steer > 0 else "Turning left."

    # ------------------------------------------------------------------
    # Remaining triggers
    # ------------------------------------------------------------------
    if trigger_type == "SPEED_CHANGE":
        return "Adjusting speed."

    if trigger_type == "PEDESTRIAN_CLOSE":
        return "Pedestrian crossing!"

    if trigger_type == "COLLISION_RISK":
        return "Collision risk! Braking hard."

    return trigger_type.replace("_", " ").capitalize() + "."


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


def _build_context(
    snap: dict,
    yolo_detections: list[dict],
    timestamp: float,
    npc_telemetry: list[list[dict]] | None = None,
) -> dict:
    """
    Extract human-readable context fields for prompt formatting.

    Args:
        snap:            Telemetry snapshot from the action event.
        yolo_detections: Full yolo_detections.json list (all frames).
        timestamp:       Event timestamp (sim seconds).
        npc_telemetry:   Optional list-of-frames from npc_telemetry.json.

    Returns dict with keys: speed, brake, throttle, steer, yolo_objects,
                            traffic_light_state, nearest_npc.
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

    # Traffic light state: infer from YOLO visibility + vehicle behaviour
    if "traffic light" in seen:
        brake = snap.get("brake", 0.0)
        tl_state = "red" if brake > 0.2 else "green"
    else:
        tl_state = "none visible"

    # Nearest NPC from npc_telemetry.json (list-of-frames format)
    nearest_npc = "none"
    if npc_telemetry:
        ego_x = snap.get("x", 0.0)
        ego_y = snap.get("y", 0.0)
        # Find frame closest in time to the trigger
        closest_frame = min(
            npc_telemetry,
            key=lambda frame: abs((frame[0].get("timestamp", 0) if frame else 0) - timestamp),
            default=None,
        )
        if closest_frame:
            best_npc = min(
                closest_frame,
                key=lambda n: (n.get("x", ego_x) - ego_x) ** 2 + (n.get("y", ego_y) - ego_y) ** 2,
                default=None,
            )
            if best_npc:
                dx = best_npc.get("x", ego_x) - ego_x
                dy = best_npc.get("y", ego_y) - ego_y
                dist = (dx ** 2 + dy ** 2) ** 0.5
                npc_speed = best_npc.get("speed_kmh", 0.0)
                actor_type = best_npc.get("actor_type", "vehicle")
                # Simplify actor_type: "vehicle.audi.a2" → "vehicle"
                kind = actor_type.split(".")[0] if "." in actor_type else actor_type
                nearest_npc = f"{kind} at {dist:.1f} m moving {npc_speed:.1f} km/h"

    return {
        "speed":               round(snap.get("speed_kmh", 0), 1),
        "brake":               round(snap.get("brake", 0), 2),
        "throttle":            round(snap.get("throttle", 0), 2),
        "steer":               round(snap.get("steer", 0), 2),
        "yolo_objects":        yolo_str,
        "traffic_light_state": tl_state,
        "nearest_npc":         nearest_npc,
    }


def _collect_trigger_frames(trigger_frames_dir: Path, trigger_type: str, step: int = 4) -> list[Path]:
    """
    Return every `step`-th frame from trigger_frames/ matching the event's trigger type.

    Files are named like: t_2093.847_BRAKING.jpg
    Sorted by their timestamp prefix so frames are in chronological order.
    The last frame (the actual trigger moment) is always included.
    """
    if not trigger_frames_dir.exists():
        return []
    frames = sorted(
        trigger_frames_dir.glob(f"*_{trigger_type}.jpg"),
        key=lambda p: float(p.stem.split("_")[1]),
    )
    if not frames:
        return []
    # Take every step-th frame; always append the last frame if not already included
    sampled = frames[::step]
    if frames[-1] not in sampled:
        sampled.append(frames[-1])
    return sampled


def _call_gpt4o(
    client,
    prompt_template: str,
    context: dict,
    image_paths: list[Path],
) -> str:
    """
    Make one GPT-4o API call with rate limiting and 429 retry.
    Sends up to len(image_paths) frames (all at detail=low) plus the text prompt.

    Returns the explanation string, or _PLACEHOLDER on any unrecoverable error.
    """
    global _last_call_time

    prompt = prompt_template.format(**context)
    messages: list[dict] = []

    valid_images = [p for p in image_paths if p.exists()]
    if valid_images:
        content: list[dict] = []
        for img in valid_images:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{_encode_image(img)}",
                    "detail": "low",   # ~$0.00085/image
                },
            })
        content.append({"type": "text", "text": prompt})
        messages.append({"role": "user", "content": content})
        logger.debug("  Sending %d frame(s) to GPT-4o", len(valid_images))
    else:
        logger.warning("No trigger frames found — sending text-only prompt.")
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
                max_tokens=50,
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

    events_path   = scenario_dir / "action_events.json"
    yolo_path     = scenario_dir / "yolo_detections.json"
    npc_path      = scenario_dir / "npc_telemetry.json"
    exp_dir       = scenario_dir / "explanations"

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

    npc_telemetry: list[list[dict]] | None = (
        json.loads(npc_path.read_text()) if npc_path.exists() else None
    )
    if npc_telemetry:
        logger.info("  Loaded NPC telemetry (%d frames)", len(npc_telemetry))

    logger.info(
        "Generating explanations for %d events in %s",
        len(events), scenario_dir.name,
    )

    scenario_id = scenario_dir.name.split("_run")[0].split("_")[0]  # e.g. "L3", "S4", "S1"

    # ------------------------------------------------------------------
    # Condition 1 — None (control)
    # ------------------------------------------------------------------
    none_entries = [_make_entry(ev, "") for ev in events]

    # ------------------------------------------------------------------
    # Conditions 2 & 3 — GPT-4o (descriptive + teleological)
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
        ctx       = _build_context(snap, yolo_detections, ts, npc_telemetry)

        # Collect every 4th trigger frame for this event (plus the final trigger frame)
        trigger_frames_dir = scenario_dir / "trigger_frames"
        image_paths = _collect_trigger_frames(trigger_frames_dir, trigger, step=4)
        logger.info(
            "  Event %d: %s @ t=%.2fs — %d frame(s)",
            ev["event_index"], trigger, ts, len(image_paths),
        )

        # Context-aware event rules — avoids GPT confusion on follow-up events
        ev_idx_val = ev["event_index"]
        prev_trigger = events[ev_idx_val - 1]["trigger_type"] if ev_idx_val > 0 else None
        next_trigger = events[ev_idx_val + 1]["trigger_type"] if ev_idx_val < len(events) - 1 else None

        if scenario_id == "S4":
            if ev_idx_val == 0:
                desc = "The vehicle has detected an emergency vehicle approaching from behind."
                tele = "I've detected an ambulance behind me."
            elif ev_idx_val == 1:
                desc = "The vehicle is steering right to pull over for the emergency vehicle."
                tele = "I'm steering right and slowing down to let the ambulance pass."
            else:
                desc = ""
                tele = ""
            descriptive_entries.append(_make_entry(ev, desc))
            teleological_entries.append(_make_entry(ev, tele))
            continue

        if scenario_id == "L3" and trigger == "ACCELERATING" and ev_idx_val == 0:
            # Narrow street entry — hardcoded; audio_start_s fires after the turn (video ~3.1s)
            desc = "The vehicle is slowing down to pass parked cars in the narrow lane."
            tele = "I'm slowing down to carefully navigate past the parked cars ahead."
            descriptive_entries.append({**_make_entry(ev, desc), "audio_start_s": 3.1})
            teleological_entries.append({**_make_entry(ev, tele), "audio_start_s": 3.1})
            continue

        elif trigger == "BRAKING" and next_trigger == "TURNING":
            # Suppress — merged explanation will appear on the TURNING event
            desc = ""
            tele = ""

        elif trigger == "TURNING" and prev_trigger == "BRAKING":
            # Merged brake+turn explanation, direction from steer
            direction = "left" if snap.get("steer", 0) > 0 else "right"
            desc = f"The vehicle is braking and turning {direction} to evade."
            tele = f"I'm braking and steering {direction} to avoid the stopped car ahead."

        elif trigger == "ACCELERATING" and prev_trigger == "TURNING":
            # Suppress — covered by merged brake+turn explanation above
            desc = ""
            tele = ""

        elif trigger == "BRAKING" and prev_trigger == "ACCELERATING":
            if ev_idx_val >= 2 and events[ev_idx_val - 2]["trigger_type"] == "TURNING":
                # S2 post-evasion pattern: BRAKING→TURNING→ACCEL→BRAKING
                desc = "The vehicle is resuming normal speed."
                tele = "I'm cruising back to normal speed."
            else:
                # End-of-sequence brake (e.g. L3) — suppress
                desc = ""
                tele = ""

        elif trigger == "ACCELERATING" and ev_idx_val > 0:
            # Non-first ACCELERATING — resuming after event
            desc = "The vehicle is resuming normal speed."
            tele = "I'm cruising back to normal speed."

        elif gpt_available and not gpt_skipped:
            try:
                desc = _call_gpt4o(client, _DESCRIPTIVE_PROMPT, ctx, image_paths)
                tele = _call_gpt4o(client, _TELEOLOGICAL_PROMPT, ctx, image_paths)
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
