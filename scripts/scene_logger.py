"""
scene_logger.py — Print a timestamped scene log for a recorded scenario run.

Reads telemetry.json, yolo_detections.json, action_events.json, and
explanations/*.json from a scenario folder, then prints:
  1. A frame table at 2 Hz resolution (every 10th frame at 20 Hz).
     Frames where an action event fired are always included.
  2. An action-events section showing what each condition would say.

Usage:
    python scripts/scene_logger.py data/scenarios/H1_PedestrianDart_run3
    python scripts/scene_logger.py data/scenarios/H1_PedestrianDart_run3 --all-frames
"""

import argparse
import json
import math
import sys
from pathlib import Path

# ---- project root on path -------------------------------------------------
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from scripts.video_pipeline.overlay import (_derive_action_state, _derive_action_text,
                                            _VEHICLE_CLASSES)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _yolo_near(yolo_detections: list[dict], timestamp: float,
               window: float = 0.5) -> list[dict]:
    """Return detections within ±window seconds of timestamp."""
    return [d for d in yolo_detections
            if abs(d.get("timestamp", 0) - timestamp) <= window]


def _yolo_labels_from_dets(dets: list[dict]) -> list[str]:
    """Return HUD-style label strings from a list of detections."""
    _MAP = {"person": "Pedestrian", "bicycle": "Cyclist", "traffic light": "Traffic Light"}
    seen: dict[str, float] = {}
    for d in dets:
        cls  = d["class_name"]
        conf = d.get("confidence", 0.0)
        if cls in _MAP and conf > seen.get(cls, 0.0):
            seen[cls] = conf
    return [f"{_MAP[cls]}({conf:.0%})" for cls, conf in
            sorted(seen.items(), key=lambda x: -x[1])]


def _yolo_summary(dets: list[dict]) -> str:
    """One-line summary of YOLO detections for a frame."""
    seen: dict[str, float] = {}
    for d in dets:
        cls  = d["class_name"]
        conf = d.get("confidence", 0.0)
        if conf > seen.get(cls, 0.0):
            seen[cls] = conf
    if not seen:
        return ""
    return ", ".join(f"{cls}({conf:.0%})"
                     for cls, conf in sorted(seen.items(), key=lambda x: -x[1]))


def _load_json(path: Path):
    if path.exists():
        return json.loads(path.read_text())
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _dist(x1, y1, x2, y2) -> float:
    return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)


def run(scenario_dir: Path, all_frames: bool = False) -> None:
    tel_path    = scenario_dir / "telemetry.json"
    yolo_path   = scenario_dir / "yolo_detections.json"
    events_path = scenario_dir / "action_events.json"
    npc_path    = scenario_dir / "npc_telemetry.json"

    if not tel_path.exists():
        print(f"ERROR: telemetry.json not found in {scenario_dir}", file=sys.stderr)
        sys.exit(1)

    telemetry       = json.loads(tel_path.read_text())
    yolo_detections = _load_json(yolo_path) or []
    events          = _load_json(events_path) or []
    npc_telemetry   = _load_json(npc_path) or []   # list[list[dict]]

    # Load explanation conditions
    exp_dir = scenario_dir / "explanations"
    cond_data: dict[str, list[dict]] = {}
    for cond in ("template", "descriptive", "teleological"):
        p = exp_dir / f"{cond}.json"
        if p.exists():
            cond_data[cond] = json.loads(p.read_text())

    # Build set of event timestamps for always-printing those frames
    event_ts_set = {ev["timestamp"] for ev in events}

    # Build event_index → explanation map per condition
    def exp_for_event(cond: str, idx: int) -> str:
        entries = cond_data.get(cond, [])
        for e in entries:
            if e.get("event_index") == idx:
                return e.get("explanation", "")
        return ""

    # -----------------------------------------------------------------------
    # Header
    # -----------------------------------------------------------------------
    has_npc = bool(npc_telemetry and any(npc_telemetry))

    print(f"\n{'=' * 72}")
    print(f"  {scenario_dir.name}  —  Scene Log")
    print(f"  {len(telemetry)} frames  |  {len(events)} action events  |  "
          f"{len(yolo_detections)} YOLO detections"
          + (f"  |  NPCs tracked" if has_npc else ""))
    print(f"{'=' * 72}\n")

    # -----------------------------------------------------------------------
    # Frame table
    # -----------------------------------------------------------------------
    STEP = 1 if all_frames else 10   # every 10th frame ≈ 2 Hz at 20 Hz
    npc_col = "  {:<22}" if has_npc else ""
    COL = "{:>6}  {:>6}  {:>5}  {:>5}  {:>8}  {:>8}  {:>8}  {:<14}  {:<28}  {}" + npc_col

    hdr_extra = ["NPC_DIST(m)"] if has_npc else []
    print(COL.format("TIME", "SPEED", "BRAKE", "STEER", "THROTTLE",
                      "EGO_X", "EGO_Y", "ACTION_STATE", "YOLO_DETECTED",
                      "TEMPLATE_TEXT", *hdr_extra))
    print("-" * (110 + (24 if has_npc else 0)))

    for i, frame in enumerate(telemetry):
        ts    = frame.get("timestamp", 0.0)
        el    = frame.get("elapsed_s", 0.0)
        speed = frame.get("speed_kmh", 0.0)
        brake = frame.get("brake", 0.0)
        steer = frame.get("steer", 0.0)
        thr   = frame.get("throttle", 0.0)
        ex    = frame.get("x", 0.0)
        ey    = frame.get("y", 0.0)

        is_event_frame = ts in event_ts_set
        if not all_frames and i % STEP != 0 and not is_event_frame:
            continue

        dets        = _yolo_near(yolo_detections, ts)
        yolo_lbls   = [d.replace("(", " (") for d in _yolo_labels_from_dets(dets)]
        yolo_str    = _yolo_summary(dets)
        action      = _derive_action_state(frame)
        has_veh     = any(d.get("class_name", "") in _VEHICLE_CLASSES for d in dets)
        tmpl_text   = _derive_action_text(frame, [l.split("(")[0].strip() for l in yolo_lbls],
                                          has_vehicle=has_veh)

        # NPC distances at this frame
        npc_str = ""
        if has_npc and i < len(npc_telemetry):
            parts = []
            for npc in npc_telemetry[i]:
                d = _dist(ex, ey, npc["x"], npc["y"])
                parts.append(f"npc{npc['index']}:{d:.1f}m@{npc['speed_kmh']:.0f}km/h")
            npc_str = "  ".join(parts)

        marker = " <<<" if is_event_frame else ""
        extra = [npc_str] if has_npc else []
        print(COL.format(
            f"{el:.2f}s",
            f"{speed:.1f}",
            f"{brake:.2f}",
            f"{steer:.2f}",
            f"{thr:.2f}",
            f"{ex:.1f}",
            f"{ey:.1f}",
            action,
            yolo_str[:28],
            tmpl_text,
            *extra,
        ) + marker)

    # -----------------------------------------------------------------------
    # Action events
    # -----------------------------------------------------------------------
    if not events:
        print("\n(no action events recorded)\n")
        return

    print(f"\n{'=' * 72}")
    print(f"  Action Events ({len(events)})")
    print(f"{'=' * 72}\n")

    for i, ev in enumerate(events):
        ts      = ev.get("timestamp", 0.0)
        el      = ev.get("telemetry_snapshot", {}).get("elapsed_s", ts)
        trigger = ev.get("trigger_type", "?")
        snap    = ev.get("telemetry_snapshot", {})
        speed   = snap.get("speed_kmh", 0.0)
        brake   = snap.get("brake", 0.0)
        ex      = snap.get("x", 0.0)
        ey      = snap.get("y", 0.0)

        dets     = _yolo_near(yolo_detections, ts, window=0.5)
        yolo_str = _yolo_summary(dets)

        print(f"[{el:.2f}s]  {trigger}  speed={speed:.1f} km/h  brake={brake:.2f}"
              f"  ego=({ex:.1f},{ey:.1f})")
        if yolo_str:
            print(f"           YOLO nearby:   {yolo_str}")

        # NPC positions at event timestamp
        if has_npc:
            # Find frame index closest to event timestamp
            best_idx = min(range(len(npc_telemetry)),
                           key=lambda k: abs(telemetry[k].get("timestamp", 0) - ts)
                           if k < len(telemetry) else 999)
            npc_at_event = npc_telemetry[best_idx] if best_idx < len(npc_telemetry) else []
            for npc in npc_at_event:
                d = _dist(ex, ey, npc["x"], npc["y"])
                print(f"           NPC[{npc['index']}] {npc['actor_type'].split('.')[-1]:<12}"
                      f"  pos=({npc['x']:.1f},{npc['y']:.1f})"
                      f"  dist={d:.1f}m  speed={npc['speed_kmh']:.0f}km/h")

        for cond in ("template", "descriptive", "teleological"):
            expl = exp_for_event(cond, i)
            if expl:
                print(f"           {cond:<14}: {expl}")
        print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Print timestamped scene log for a recorded AdaptTrust scenario.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Example:\n  python scripts/scene_logger.py data/scenarios/H1_PedestrianDart_run3",
    )
    parser.add_argument("scenario_dir", help="Path to recorded scenario folder")
    parser.add_argument("--all-frames", action="store_true",
                        help="Print every frame instead of 2 Hz subset")
    args = parser.parse_args()

    run(Path(args.scenario_dir), all_frames=args.all_frames)


if __name__ == "__main__":
    main()
