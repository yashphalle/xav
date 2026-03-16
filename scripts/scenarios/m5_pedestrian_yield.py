"""
m5_pedestrian_yield.py — Ego yields to a pedestrian crossing the road

Criticality: MEDIUM
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


class M5PedestrianYield(ScenarioBase):
    def __init__(self, **kwargs):
        super().__init__(map_name="Town01", spawn_index=0, **kwargs)

    def run(self, ap=None, rec=None) -> dict:
        self.world.set_weather(carla.WeatherParameters.CloudySunset)

        npcs = []
        bp_lib = self.world.get_blueprint_library()
        spawn_points = self.world.get_map().get_spawn_points()

        # Spawn 1 pedestrian offset from the road, walking across the ego's path
        try:
            walker_bp = bp_lib.filter("walker.pedestrian.*")[0]
            base_loc = spawn_points[1].location
            walker_location = carla.Location(
                x=base_loc.x + 5,
                y=base_loc.y + 3,
                z=base_loc.z,
            )
            walker_transform = carla.Transform(walker_location)
            walker = self.world.try_spawn_actor(walker_bp, walker_transform)
            if walker is not None:
                # Walker walks in a fixed direction across the road — no AI controller needed
                walker.apply_control(carla.WalkerControl(
                    speed=1.0,
                    direction=carla.Vector3D(x=0, y=-1, z=0),
                ))
                npcs.append(walker)
        except Exception:
            pass

        if ap is None:
            ap = AutopilotController(self.ego, self.traffic_manager, target_speed_kmh=30)
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
            "map": "Town01",
            "duration_s": DURATION,
            "npc_count": len(npcs),
        }


if __name__ == "__main__":
    import json
    s = M5PedestrianYield(scenario_id="m5_pedestrian_yield_test")
    s.setup()
    try:
        result = s.run()
        print(json.dumps(result, indent=2))
    finally:
        s.clean_up()
