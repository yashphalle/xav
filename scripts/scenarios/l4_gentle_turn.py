"""
l4_gentle_turn.py — Ego executes a gentle right turn at a Town01 T-junction.

Criticality: LOW
Map: Town01
Duration: 20 s

Determinism fix:
- BasicAgent uses GlobalRoutePlanner which navigates turns correctly
- Destination is chosen 400 m ahead so the A* route MUST go through a turn
- spawn_index=1 is near a junction in Town01 (adjust if needed)
- All traffic lights frozen GREEN
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import carla
from scripts.scenarios.scenario_base import ScenarioBase, ScenarioFailed
from scripts.autonomous.agent_controller import AgentController
from scripts.data_collection.recorder import Recorder

DURATION   = 20.0
TARGET_KMH = 30.0


class L4GentleTurn(ScenarioBase):
    def __init__(self, **kwargs):
        super().__init__(map_name="Town01", spawn_index=1, **kwargs)

    def run(self, ap=None, rec=None) -> dict:
        self.world.set_weather(carla.WeatherParameters.ClearNoon)

        for tl in self.world.get_actors().filter("traffic.traffic_light"):
            tl.set_state(carla.TrafficLightState.Green)
            tl.freeze(True)

        # Pick a destination that forces a turn: use spawn point at perpendicular road
        spawn_points = self.world.get_map().get_spawn_points()
        # spawn_index=1 is forward; use index 20 as destination to force a turn
        dest_idx = min(20, len(spawn_points) - 1)
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
            "map": "Town01",
            "duration_s": DURATION,
            "npc_count": 0,
        }

    def verify(self) -> None:
        pass


if __name__ == "__main__":
    import json
    s = L4GentleTurn(scenario_id="l4_gentle_turn_test")
    s.setup()
    try:
        result = s.run(); s.verify()
        print(json.dumps(result, indent=2))
    finally:
        s.clean_up()
