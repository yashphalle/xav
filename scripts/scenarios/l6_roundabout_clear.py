"""
l6_roundabout_clear.py — Ego navigates a clear roundabout with no other traffic.

Criticality: LOW
Map: Town03  (has a prominent roundabout at the town centre)
Duration: 25 s

Determinism fix:
- spawn_index=7 is near Town03's central roundabout (adjust if needed)
- Destination is a spawn point on the far side of the roundabout
- BasicAgent uses GlobalRoutePlanner which handles roundabout navigation
- All TLs green so no unexpected stops
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import carla
from scripts.scenarios.scenario_base import ScenarioBase, ScenarioFailed
from scripts.autonomous.agent_controller import AgentController
from scripts.data_collection.recorder import Recorder

DURATION   = 25.0
TARGET_KMH = 20.0   # slow for roundabout


class L6RoundaboutClear(ScenarioBase):
    def __init__(self, **kwargs):
        super().__init__(map_name="Town03", spawn_index=7, **kwargs)

    def run(self, ap=None, rec=None) -> dict:
        self.world.set_weather(carla.WeatherParameters.ClearNoon)

        for tl in self.world.get_actors().filter("traffic.traffic_light"):
            tl.set_state(carla.TrafficLightState.Green)
            tl.freeze(True)

        spawn_points = self.world.get_map().get_spawn_points()
        # Destination on far side of roundabout
        dest_idx = min(75, len(spawn_points) - 1)
        dest = spawn_points[dest_idx].location

        if ap is None:
            ap = AgentController(self.ego, self.world,
                                 target_speed_kmh=TARGET_KMH,
                                 ignore_traffic_lights=True)
            ap.set_destination(dest)
        ap.enable()

        if rec is None:
            rec = Recorder(self); rec.__enter__(); _owns_rec = True
        else:
            _owns_rec = False

        try:
            start = self.world.get_snapshot().timestamp.elapsed_seconds
            elapsed = 0.0
            while elapsed < DURATION:
                frame   = self.tick()
                ap.update(frame)
                rec.record(frame)
                elapsed = frame["timestamp"] - start
        finally:
            if _owns_rec:
                rec.__exit__(None, None, None)

        ap.disable()

        return {
            "scenario_id": self.scenario_id,
            "criticality": "low",
            "map": "Town03",
            "duration_s": DURATION,
            "npc_count": 0,
        }

    def verify(self) -> None:
        pass


if __name__ == "__main__":
    import json
    s = L6RoundaboutClear(scenario_id="l6_roundabout_clear_test")
    s.setup()
    try:
        result = s.run(); s.verify()
        print(json.dumps(result, indent=2))
    finally:
        s.clean_up()
