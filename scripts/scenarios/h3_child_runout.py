"""
h3_child_runout.py — Child runs out from sidewalk; ego emergency brakes.

Criticality: HIGH
Map: Town02
Duration: 20s

Reliability fixes:
- Walker placed 18m ahead using waypoints, 3.5m to the right (sidewalk)
- Walk direction perpendicular to road (into ego's lane)
- Speed-gated trigger: only fires when ego is moving > MIN_SPEED_KMH
- Fallback at FALLBACK_S
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import carla
from scripts.scenarios.scenario_base import ScenarioBase
from scripts.autonomous.autopilot_controller import AutopilotController
from scripts.data_collection.recorder import Recorder

DURATION      = 20.0
MIN_SPEED_KMH = 10.0
WARMUP_S      =  4.0
FALLBACK_S    = 11.0


class H3ChildRunout(ScenarioBase):
    def __init__(self, **kwargs):
        super().__init__(map_name="Town02", spawn_index=0, **kwargs)

    def run(self, ap=None, rec=None) -> dict:
        self.world.set_weather(carla.WeatherParameters.WetCloudyNoon)

        npcs = []
        bp_lib = self.world.get_blueprint_library()

        # Prefer a child pedestrian blueprint
        child_bps = [b for b in bp_lib.filter("walker.pedestrian.*")
                     if "0012" in b.id or "0013" in b.id or "0014" in b.id]
        walker_bp = child_bps[0] if child_bps else bp_lib.filter("walker.pedestrian.*")[0]

        # --- Place walker 18m ahead, 3.5m to the right ---
        ego_wp    = self.world.get_map().get_waypoint(self.ego.get_location())
        ahead_wps = ego_wp.next(18.0)
        walker    = None
        walk_dir  = carla.Vector3D(x=0, y=-1, z=0)

        if ahead_wps:
            fwd   = ahead_wps[0].transform.get_forward_vector()
            right = carla.Vector3D(x=-fwd.y, y=fwd.x, z=0.0)
            loc   = (
                ahead_wps[0].transform.location
                + carla.Location(x=right.x * 3.5, y=right.y * 3.5, z=0.5)
            )
            walker   = self.world.try_spawn_actor(walker_bp, carla.Transform(loc, carla.Rotation()))
            walk_dir = carla.Vector3D(x=-right.x, y=-right.y, z=0.0)

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
            start   = self.world.get_snapshot().timestamp.elapsed_seconds
            elapsed = 0.0

            while elapsed < DURATION:
                frame   = self.tick()
                ap.update(frame)
                rec.record(frame)
                elapsed = frame["timestamp"] - start

                fire = (
                    not critical_triggered
                    and elapsed >= WARMUP_S
                    and (frame["speed_kmh"] > MIN_SPEED_KMH or elapsed >= FALLBACK_S)
                )

                if fire:
                    critical_triggered = True

                    if walker and walker.is_alive:
                        walker.apply_control(carla.WalkerControl(
                            speed=3.5,
                            direction=walk_dir,
                        ))

                    with ap.override():
                        for _ in range(30):   # ~1.5 s
                            self.ego.apply_control(
                                carla.VehicleControl(brake=1.0, throttle=0.0)
                            )
                            frame   = self.tick()
                            ap.update(frame)
                            rec.record(frame)
                            elapsed = frame["timestamp"] - start
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
            "duration_s": DURATION,
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
