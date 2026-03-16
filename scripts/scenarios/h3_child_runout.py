"""
h3_child_runout.py — Child pedestrian runs out from sidewalk onto road in front of ego

Criticality: HIGH
Map: Town02
Duration: 20s
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import carla
from scripts.scenarios.scenario_base import ScenarioBase
from scripts.autonomous.autopilot_controller import AutopilotController
from scripts.data_collection.recorder import Recorder


class H3ChildRunout(ScenarioBase):
    def __init__(self, **kwargs):
        super().__init__(map_name="Town02", spawn_index=0, **kwargs)

    def run(self, ap=None, rec=None) -> dict:
        self.world.set_weather(carla.WeatherParameters.WetCloudyNoon)

        npcs = []
        bp_lib = self.world.get_blueprint_library()
        spawn_points = self.world.get_map().get_spawn_points()

        # Spawn child pedestrian walker on sidewalk
        # Prefer child walker blueprint if available
        child_bps = bp_lib.filter("walker.pedestrian.0013")
        if len(child_bps) > 0:
            walker_bp = child_bps[0]
        else:
            walker_bps = bp_lib.filter("walker.pedestrian.*")
            walker_bp = walker_bps[0]

        walker_transform = carla.Transform(
            spawn_points[1].location + carla.Location(x=3, y=2, z=0.5),
            carla.Rotation()
        )
        walker = self.world.try_spawn_actor(walker_bp, walker_transform)
        if walker:
            npcs.append(walker)

        if ap is None:
            ap = AutopilotController(self.ego, self.traffic_manager, target_speed_kmh=25)
        ap.enable()

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

                # At t=7s: child runs onto road, ego performs emergency brake
                if elapsed >= 7.0 and not critical_triggered:
                    critical_triggered = True
                    # Make child dash onto road at an angle
                    if walker and walker.is_alive:
                        walker.apply_control(carla.WalkerControl(
                            speed=3.5,
                            direction=carla.Vector3D(x=-1, y=0.2, z=0),
                        ))
                    # Force ego emergency brake
                    with ap.override():
                        for _ in range(25):  # ~1.25s at 20Hz
                            self.ego.apply_control(carla.VehicleControl(brake=1.0, throttle=0.0))
                            frame = self.tick()
                            ap.update(frame)
                            rec.record(frame)
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
            "map": "Town02",
            "duration_s": 20,
            "npc_count": len(npcs),
        }


if __name__ == "__main__":
    import json
    s = H3ChildRunout(scenario_id="h3_child_runout_test")
    s.setup()
    try:
        result = s.run()
        print(json.dumps(result, indent=2))
    finally:
        s.clean_up()
