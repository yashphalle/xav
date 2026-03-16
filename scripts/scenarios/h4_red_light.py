"""
h4_red_light.py — Ego approaches and stops at red traffic light intersection

Criticality: HIGH
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


class H4RedLight(ScenarioBase):
    def __init__(self, **kwargs):
        super().__init__(map_name="Town03", spawn_index=0, **kwargs)

    def run(self, ap=None, rec=None) -> dict:
        self.world.set_weather(carla.WeatherParameters.WetCloudyNoon)

        npcs = []
        bp_lib = self.world.get_blueprint_library()
        spawn_points = self.world.get_map().get_spawn_points()

        if ap is None:
            ap = AutopilotController(self.ego, self.traffic_manager, target_speed_kmh=45)
        ap.enable()

        # Ensure autopilot respects all traffic lights (ignore_lights_percentage = 0)
        self.traffic_manager.ignore_lights_percentage(self.ego, 0)

        if rec is None:
            rec = Recorder(self)
            rec.__enter__()
            _owns_rec = True
        else:
            _owns_rec = False

        critical_triggered = False

        try:
            start = self.world.get_snapshot().timestamp.elapsed_seconds
            elapsed = 0.0
            while elapsed < 20:
                frame = self.tick()
                ap.update(frame)
                rec.record(frame)
                elapsed = frame["timestamp"] - start

                # No forced brake — TM handles red light stopping naturally.
                # Mark critical event time for logging purposes only.
                if elapsed >= 10.0 and not critical_triggered:
                    critical_triggered = True
        finally:
            if _owns_rec:
                rec.__exit__(None, None, None)

        for npc in npcs:
            if npc.is_alive:
                npc.destroy()
        ap.disable()

        return {
            "scenario_id": self.scenario_id,
            "criticality": "high",
            "map": "Town03",
            "duration_s": 20,
            "npc_count": len(npcs),
        }


if __name__ == "__main__":
    import json
    s = H4RedLight(scenario_id="h4_red_light_test")
    s.setup()
    try:
        result = s.run()
        print(json.dumps(result, indent=2))
    finally:
        s.clean_up()
