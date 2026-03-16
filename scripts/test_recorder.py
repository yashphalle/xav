"""
test_recorder.py — End-to-end pipeline test (no GPT-4o required).

Verifies: CARLA connect → ego spawn → autopilot → Recorder (video + YOLO +
telemetry + action events) → clean exit.

Run from repo root:
    conda activate carla-xav
    python scripts/test_recorder.py

CARLA server must already be running:
    cd ~/carla && ./CarlaUE4.sh -quality-level=Low
"""

import json
import sys
import time
from pathlib import Path

# Allow imports from repo root regardless of working directory
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import carla

from scripts.autonomous.autopilot_controller import AutopilotController
from scripts.data_collection.recorder import Recorder
from scripts.scenarios.scenario_base import ScenarioBase

RECORD_SECONDS = 15


# ---------------------------------------------------------------------------
# Concrete scenario — just drive with autopilot for N seconds
# ---------------------------------------------------------------------------

class _RecorderTestScenario(ScenarioBase):
    def run(self) -> dict:
        ap = AutopilotController(self.ego, self.traffic_manager)
        ap.enable()

        with Recorder(self) as rec:
            start = self.world.get_snapshot().timestamp.elapsed_seconds
            prev_log = -1.0

            while True:
                frame = self.tick()
                ap.update(frame)
                rec.record(frame)

                elapsed = frame["timestamp"] - start
                # Print a one-liner every 3 s so the user sees progress
                if int(elapsed) % 3 == 0 and int(elapsed) != int(prev_log):
                    prev_log = elapsed
                    print(
                        f"  t={elapsed:5.1f}s | "
                        f"speed={frame['speed_kmh']:5.1f} km/h | "
                        f"detections={rec.detection_count:4d} | "
                        f"triggers={len(self._action_events)}"
                    )

                if elapsed >= RECORD_SECONDS:
                    break

        ap.disable()
        return rec.summary()


# ---------------------------------------------------------------------------
# Pre-flight CARLA check
# ---------------------------------------------------------------------------

def _check_carla(host: str = "localhost", port: int = 2000, timeout: float = 3.0) -> bool:
    try:
        client = carla.Client(host, port)
        client.set_timeout(timeout)
        client.get_server_version()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    print("=" * 60)
    print("AdaptTrust — Recorder pipeline test")
    print("=" * 60)

    print("\n[1/4] Checking CARLA server …")
    if not _check_carla():
        print(
            "\nERROR: Cannot connect to CARLA on localhost:2000.\n"
            "Start the server first:\n"
            "  cd ~/carla && ./CarlaUE4.sh -quality-level=Low\n"
            "Then re-run this script."
        )
        return 1
    print("      CARLA is running.")

    print(f"\n[2/4] Setting up scenario (Town01, {RECORD_SECONDS}s) …")
    scenario = _RecorderTestScenario(
        map_name="Town01",
        spawn_index=0,
        scenario_id="recorder_test_run1",
    )

    print(f"\n[3/4] Recording …")
    try:
        with scenario as s:
            result = s.run()
    except Exception as e:
        print(f"\nERROR during recording: {e}")
        raise

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    out = scenario.output_dir
    video_path   = out / "video.mp4"
    telem_path   = out / "telemetry.json"
    yolo_path    = out / "yolo_detections.json"
    events_path  = out / "action_events.json"

    video_mb = video_path.stat().st_size / 1e6 if video_path.exists() else 0
    telem_count  = len(json.loads(telem_path.read_text()))  if telem_path.exists()  else 0
    yolo_count   = len(json.loads(yolo_path.read_text()))   if yolo_path.exists()   else 0
    events       = json.loads(events_path.read_text())       if events_path.exists() else []

    print("\n[4/4] Results")
    print("-" * 60)
    print(f"  Output dir      : {out}")
    print(f"  video.mp4       : {'OK' if video_path.exists() else 'MISSING'} ({video_mb:.1f} MB, {result['frames_recorded']} frames)")
    print(f"  telemetry.json  : {'OK' if telem_path.exists() else 'MISSING'} ({telem_count} entries)")
    print(f"  yolo_detections : {'OK' if yolo_path.exists() else 'MISSING'} ({yolo_count} detections)")
    print(f"  action_events   : {'OK' if events_path.exists() else 'MISSING'} ({len(events)} events)")

    if result["detections_by_class"]:
        print(f"\n  YOLO classes seen:")
        for cls, count in sorted(result["detections_by_class"].items(), key=lambda x: -x[1]):
            print(f"    {cls:<20} {count}")

    if events:
        print(f"\n  Action triggers fired:")
        for ev in events:
            has_frame = "frame_path" in ev
            print(f"    t={ev['timestamp']:.2f}s  {ev['trigger_type']:<20} frame={'yes' if has_frame else 'no'}")

    trigger_dir = out / "trigger_frames"
    if trigger_dir.exists():
        jpgs = list(trigger_dir.glob("*.jpg"))
        print(f"\n  Trigger JPEGs   : {len(jpgs)} saved in {trigger_dir.name}/")

    all_ok = all([
        video_path.exists(),
        telem_path.exists(),
        yolo_path.exists(),
        events_path.exists(),
    ])

    print("-" * 60)
    if all_ok:
        print("PASSED — all output files present.")
    else:
        print("PARTIAL — some output files missing (see above).")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
