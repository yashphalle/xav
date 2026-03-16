"""
m4_yellow_light.py — Ego approaches an intersection and encounters a yellow/red traffic light

Criticality: MEDIUM
Map: Town03
Duration: 25s
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import carla
from scripts.scenarios.scenario_base import ScenarioBase
from scripts.autonomous.autopilot_controller import AutopilotController
from scripts.data_collection.recorder import Recorder


class M4YellowLight(ScenarioBase):
    def __init__(self, **kwargs):
        super().__init__(map_name="Town03", spawn_index=0, **kwargs)

    def run(self, ap=None, rec=None) -> dict:
        self.world.set_weather(carla.WeatherParameters.CloudySunset)

        npcs = []
        bp_lib = self.world.get_blueprint_library()
        spawn_points = self.world.get_map().get_spawn_points()

        # No NPCs — focus on ego's interaction with traffic lights
        # TM autopilot naturally obeys traffic lights, capturing yellow/red behaviour

        if ap is None:
            ap = AutopilotController(self.ego, self.traffic_manager, target_speed_kmh=40)
        ap.enable()

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

        for npc in npcs:
            if npc.is_alive:
                npc.destroy()
        ap.disable()

        return {
            "scenario_id": self.scenario_id,
            "criticality": "medium",
            "map": "Town03",
            "duration_s": DURATION,
            "npc_count": len(npcs),
        }


if __name__ == "__main__":
    import json
    s = M4YellowLight(scenario_id="m4_yellow_light_test")
    s.setup()
    try:
        result = s.run()
        print(json.dumps(result, indent=2))
    finally:
        s.clean_up()
