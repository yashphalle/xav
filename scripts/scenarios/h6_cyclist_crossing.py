"""
h6_cyclist_crossing.py — Cyclist crosses intersection; ego emergency brakes to yield.

Criticality: HIGH
Map: Town03
Duration: 20s

Reliability fixes:
- Cyclist spawned 22m ahead using waypoints, offset 5m to right (approaching lane)
- Speed-gated trigger: only fires when ego is actually moving
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
MIN_SPEED_KMH = 12.0
WARMUP_S      =  5.0
FALLBACK_S    = 12.0


class H6CyclistCrossing(ScenarioBase):
    def __init__(self, **kwargs):
        super().__init__(map_name="Town03", spawn_index=2, **kwargs)

    def run(self, ap=None, rec=None) -> dict:
        self.world.set_weather(carla.WeatherParameters.WetCloudyNoon)

        npcs = []
        bp_lib = self.world.get_blueprint_library()

        # Find a bicycle blueprint
        cyclist_bp = None
        for name in ("vehicle.gazelle.omafiets", "vehicle.bh.crossbike",
                     "vehicle.diamondback.century", "vehicle.carlacola.cybertruck"):
            try:
                cyclist_bp = bp_lib.find(name)
                break
            except (IndexError, Exception):
                continue
        if cyclist_bp is None:
            bikes = [b for b in bp_lib.filter("vehicle.*")
                     if any(k in b.id for k in ("bike", "cycle", "cross", "gazelle"))]
            cyclist_bp = bikes[0] if bikes else bp_lib.filter("vehicle.*")[0]

        # Spawn cyclist 22m ahead, 5m to the right — crossing from the side
        ego_wp    = self.world.get_map().get_waypoint(self.ego.get_location())
        ahead_wps = ego_wp.next(22.0)
        cyclist   = None

        if ahead_wps:
            fwd   = ahead_wps[0].transform.get_forward_vector()
            right = carla.Vector3D(x=-fwd.y, y=fwd.x, z=0.0)
            loc   = (
                ahead_wps[0].transform.location
                + carla.Location(x=right.x * 5.0, y=right.y * 5.0, z=0.3)
            )
            # Cyclist faces perpendicular — crossing left to right from ego's view
            cyclist_rot = carla.Rotation(yaw=ahead_wps[0].transform.rotation.yaw + 90)
            cyclist = self.world.try_spawn_actor(cyclist_bp, carla.Transform(loc, cyclist_rot))

        if cyclist:
            npcs.append(cyclist)
            cyclist.set_autopilot(True, self.traffic_manager.get_port())
            self.traffic_manager.vehicle_percentage_speed_difference(cyclist, 70)   # slow
            self.traffic_manager.ignore_lights_percentage(cyclist, 100)

        if ap is None:
            ap = AutopilotController(self.ego, self.traffic_manager, target_speed_kmh=35)
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
                    with ap.override():
                        for _ in range(28):   # ~1.4 s
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
            "map": "Town03",
            "duration_s": DURATION,
            "npc_count": len(npcs),
        }


if __name__ == "__main__":
    import json
    s = H6CyclistCrossing(scenario_id="h6_cyclist_crossing_test")
    s.setup()
    try:
        result = s.run()
        print(json.dumps(result, indent=2))
    finally:
        s.clean_up()
