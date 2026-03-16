"""
h1_pedestrian_dash.py — Pedestrian dashes across road; ego emergency brakes.

Criticality: HIGH
Map: Town01
Duration: 20s

Reliability fixes:
- Walker placed 20m ahead of ego using waypoints (not fixed world offset)
- Walk direction computed perpendicular to road so walker crosses the lane
- Critical event fires when speed_kmh > MIN_SPEED_KMH, not at fixed time —
  prevents the brake override being a no-op on a stationary vehicle
- Fallback fires at FALLBACK_TIME so the scenario never silently skips
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import carla
from scripts.scenarios.scenario_base import ScenarioBase
from scripts.autonomous.autopilot_controller import AutopilotController
from scripts.data_collection.recorder import Recorder

DURATION      = 20.0
MIN_SPEED_KMH = 12.0   # only fire when ego is actually moving
WARMUP_S      =  5.0   # minimum seconds before critical event is allowed
FALLBACK_S    = 12.0   # fire regardless after this many elapsed seconds


class H1PedestrianDash(ScenarioBase):
    def __init__(self, **kwargs):
        super().__init__(map_name="Town01", spawn_index=0, **kwargs)

    def run(self, ap=None, rec=None) -> dict:
        self.world.set_weather(carla.WeatherParameters.WetCloudyNoon)

        npcs = []
        bp_lib     = self.world.get_blueprint_library()
        walker_bps = bp_lib.filter("walker.pedestrian.*")
        walker_bp  = walker_bps[int(len(walker_bps) * 0.3)]   # pick an adult

        # --- Place walker 20m ahead of ego, 4m to the right (sidewalk side) ---
        ego_wp    = self.world.get_map().get_waypoint(self.ego.get_location())
        ahead_wps = ego_wp.next(20.0)
        walker    = None
        walk_dir  = carla.Vector3D(x=0, y=-1, z=0)   # world-space fallback

        if ahead_wps:
            fwd   = ahead_wps[0].transform.get_forward_vector()
            right = carla.Vector3D(x=-fwd.y, y=fwd.x, z=0.0)       # 90° right of road
            loc   = (
                ahead_wps[0].transform.location
                + carla.Location(x=right.x * 4.0, y=right.y * 4.0, z=0.5)
            )
            walker = self.world.try_spawn_actor(walker_bp, carla.Transform(loc, carla.Rotation()))
            walk_dir = carla.Vector3D(x=-right.x, y=-right.y, z=0.0)  # 90° left = into road

        if walker:
            npcs.append(walker)

        # --- Ego autopilot ---
        if ap is None:
            ap = AutopilotController(self.ego, self.traffic_manager, target_speed_kmh=30)
        ap.enable()

        # --- Recording loop ---
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

                    # Pedestrian dashes across road
                    if walker and walker.is_alive:
                        walker.apply_control(carla.WalkerControl(speed=4.0, direction=walk_dir))

                    # Forced emergency brake — guarantees BRAKING trigger
                    with ap.override():
                        for _ in range(35):   # ~1.75 s at 20 Hz
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
            "map": "Town01",
            "duration_s": DURATION,
            "npc_count": len(npcs),
        }


if __name__ == "__main__":
    import json
    s = H1PedestrianDash(scenario_id="h1_pedestrian_dash_test")
    s.setup()
    try:
        result = s.run()
        print(json.dumps(result, indent=2))
    finally:
        s.clean_up()
