"""
l3_green_light.py — Ego approaches and proceeds through a green traffic light

Criticality: LOW
Map: Town03
Duration: 20s
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import carla
from scripts.scenarios.scenario_base import ScenarioBase
from scripts.autonomous.autopilot_controller import AutopilotController
from scripts.data_collection.recorder import Recorder


class L3GreenLight(ScenarioBase):
    def __init__(self, **kwargs):
        super().__init__(map_name="Town03", spawn_index=0, **kwargs)

    def run(self, ap=None, rec=None) -> dict:
        # Set weather
        self.world.set_weather(carla.WeatherParameters.ClearNoon)

        # No NPCs — scenario captures the green-light-proceed event via autopilot
        npcs = []

        # Enable autopilot on ego
        # Autopilot naturally obeys traffic lights; scenario just records the event
        if ap is None:
            ap = AutopilotController(self.ego, self.traffic_manager, target_speed_kmh=30)
        ap.target_speed_kmh = 30
        ap._configure_tm()
        ap.enable()

        # Recording loop
        if rec is None:
            rec = Recorder(self)
            rec.__enter__()
            _owns_rec = True
        else:
            _owns_rec = False

        DURATION = 20

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
            "map": "Town03",
            "duration_s": DURATION,
            "npc_count": len(npcs),
        }


if __name__ == "__main__":
    import json
    s = L3GreenLight(scenario_id="l3_green_light_test")
    s.setup()
    try:
        result = s.run()
        print(json.dumps(result, indent=2))
    finally:
        s.clean_up()
