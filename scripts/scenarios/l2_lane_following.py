"""
l2_lane_following.py — Ego follows a straight urban lane with no traffic

Criticality: LOW
Map: Town01
Duration: 25s
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import carla
from scripts.scenarios.scenario_base import ScenarioBase
from scripts.autonomous.autopilot_controller import AutopilotController
from scripts.data_collection.recorder import Recorder


class L2LaneFollowing(ScenarioBase):
    def __init__(self, **kwargs):
        super().__init__(map_name="Town01", spawn_index=0, **kwargs)

    def run(self, ap=None, rec=None) -> dict:
        # Set weather
        self.world.set_weather(carla.WeatherParameters.ClearNoon)

        # No NPCs for this scenario
        npcs = []

        # Enable autopilot on ego
        if ap is None:
            ap = AutopilotController(self.ego, self.traffic_manager, target_speed_kmh=40)
        ap.target_speed_kmh = 40
        ap._configure_tm()
        ap.enable()

        # Recording loop
        if rec is None:
            rec = Recorder(self)
            rec.__enter__()
            _owns_rec = True
        else:
            _owns_rec = False

        DURATION = 25

        try:
            start = self.world.get_snapshot().timestamp.elapsed_seconds
            while True:
                frame = self.tick()
                ap.update(frame)
                rec.record(frame)
                if frame["timestamp"] - start >= DURATION:
                    break
        finally:
            if _owns_rec:
                rec.__exit__(None, None, None)

        ap.disable()
        return {
            "scenario_id": self.scenario_id,
            "criticality": "low",
            "map": "Town01",
            "duration_s": DURATION,
            "npc_count": len(npcs),
        }


if __name__ == "__main__":
    import json
    s = L2LaneFollowing(scenario_id="l2_lane_following_test")
    s.setup()
    try:
        result = s.run()
        print(json.dumps(result, indent=2))
    finally:
        s.clean_up()
