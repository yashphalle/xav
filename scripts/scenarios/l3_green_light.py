"""
l3_green_light.py — Ego approaches and passes through an intersection under GREEN light.

Criticality: LOW
Map: Town03
Duration: 25 s

Determinism fix:
- All traffic lights explicitly set GREEN and frozen before ego moves
- BasicAgent follows route through intersection at 40 km/h
- No NPCs; clean passage — demonstrates normal flow
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import carla
from scripts.scenarios.scenario_base import ScenarioBase, ScenarioFailed
from scripts.autonomous.agent_controller import AgentController
from scripts.data_collection.recorder import Recorder

DURATION   = 25.0
TARGET_KMH = 40.0


def _dest(world, ego, dist_m=500.0):
    wp = world.get_map().get_waypoint(ego.get_location())
    wps = wp.next(dist_m)
    return wps[0].transform.location if wps \
        else world.get_map().get_spawn_points()[-1].location


class L3GreenLight(ScenarioBase):
    def __init__(self, **kwargs):
        super().__init__(map_name="Town03", spawn_index=0, **kwargs)

    def run(self, ap=None, rec=None) -> dict:
        self.world.set_weather(carla.WeatherParameters.ClearNoon)

        # Freeze all lights green — ego passes through without stopping
        for tl in self.world.get_actors().filter("traffic.traffic_light"):
            tl.set_state(carla.TrafficLightState.Green)
            tl.freeze(True)

        if ap is None:
            ap = AgentController(self.ego, self.world,
                                 target_speed_kmh=TARGET_KMH,
                                 ignore_traffic_lights=True)
            ap.set_destination(_dest(self.world, self.ego))
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
    s = L3GreenLight(scenario_id="l3_green_light_test")
    s.setup()
    try:
        result = s.run(); s.verify()
        print(json.dumps(result, indent=2))
    finally:
        s.clean_up()
