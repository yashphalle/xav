"""
h6_cyclist_crossing.py — Cyclist crosses intersection; ego emergency-brakes.

Criticality: HIGH
Map: Town03
Duration: 20 s

Determinism guarantee:
1. All TLs frozen GREEN — ego approaches at 35 km/h unimpeded
2. Cyclist spawned 22 m ahead, 5 m to the right, facing perpendicular (crossing dir)
3. At trigger: cyclist TM set to cross (ignore lights); simultaneously ap.override()
   forces ego brake=0.8 for 1.4 s
4. Speed gate ensures ego is moving when brake fires
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import carla
from scripts.scenarios.scenario_base import ScenarioBase, ScenarioFailed
from scripts.autonomous.agent_controller import AgentController
from scripts.data_collection.recorder import Recorder

DURATION      = 20.0
TARGET_KMH    = 35.0
MIN_SPEED_KMH = 12.0
WARMUP_S      =  5.0
FALLBACK_S    = 12.0


def _dest(world, ego, dist_m=500.0):
    wp = world.get_map().get_waypoint(ego.get_location())
    wps = wp.next(dist_m)
    return wps[0].transform.location if wps \
        else world.get_map().get_spawn_points()[-1].location


class H6CyclistCrossing(ScenarioBase):
    def __init__(self, **kwargs):
        super().__init__(map_name="Town03", spawn_index=2, **kwargs)

    def run(self, ap=None, rec=None) -> dict:
        self.world.set_weather(carla.WeatherParameters.WetCloudyNoon)

        for tl in self.world.get_actors().filter("traffic.traffic_light"):
            tl.set_state(carla.TrafficLightState.Green)
            tl.freeze(True)

        # Find a bicycle blueprint
        bp_lib = self.world.get_blueprint_library()
        cyclist_bp = None
        for name in ("vehicle.gazelle.omafiets", "vehicle.bh.crossbike",
                     "vehicle.diamondback.century"):
            try:
                cyclist_bp = bp_lib.find(name)
                break
            except Exception:
                continue
        if cyclist_bp is None:
            bikes = [b for b in bp_lib.filter("vehicle.*")
                     if any(k in b.id for k in ("bike", "cycle", "cross", "gazelle"))]
            cyclist_bp = bikes[0] if bikes else bp_lib.filter("vehicle.*")[0]

        # Spawn cyclist 22 m ahead, 5 m to the right, facing perpendicular
        ego_wp    = self.world.get_map().get_waypoint(self.ego.get_location())
        ahead_wps = ego_wp.next(22.0)
        cyclist = None
        if ahead_wps:
            fwd   = ahead_wps[0].transform.get_forward_vector()
            right = carla.Vector3D(x=-fwd.y, y=fwd.x, z=0.0)
            loc   = (
                ahead_wps[0].transform.location
                + carla.Location(x=right.x * 5.0, y=right.y * 5.0, z=0.3)
            )
            cyclist_rot = carla.Rotation(
                yaw=ahead_wps[0].transform.rotation.yaw + 90
            )
            cyclist = self.world.try_spawn_actor(
                cyclist_bp, carla.Transform(loc, cyclist_rot)
            )

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

        critical_triggered = False

        try:
            start = self.world.get_snapshot().timestamp.elapsed_seconds
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
                    # Cyclist crosses — TM with full throttle, ignore lights
                    if cyclist and cyclist.is_alive:
                        cyclist.set_autopilot(True, self.traffic_manager.get_port())
                        self.traffic_manager.ignore_lights_percentage(cyclist, 100)
                        self.traffic_manager.vehicle_percentage_speed_difference(cyclist, -80)
                    # Ego emergency-brakes
                    with ap.override():
                        for _ in range(28):   # ~1.4 s
                            self.ego.apply_control(
                                carla.VehicleControl(brake=0.8, throttle=0.0)
                            )
                            frame   = self.tick()
                            ap.update(frame)
                            rec.record(frame)
                            elapsed = frame["timestamp"] - start

        finally:
            if _owns_rec:
                rec.__exit__(None, None, None)

        if cyclist and cyclist.is_alive: cyclist.destroy()
        ap.disable()

        return {
            "scenario_id": self.scenario_id,
            "criticality": "high",
            "map": "Town03",
            "duration_s": DURATION,
            "npc_count": 1 if cyclist else 0,
        }

    def verify(self) -> None:
        braking = [e for e in self._action_events
                   if e["trigger_type"] == "BRAKING"]
        if not braking:
            raise ScenarioFailed(
                f"{self.scenario_id}: expected BRAKING trigger. "
                f"Got: {[e['trigger_type'] for e in self._action_events]}"
            )


if __name__ == "__main__":
    import json
    s = H6CyclistCrossing(scenario_id="h6_cyclist_crossing_test")
    s.setup()
    try:
        result = s.run()
        s.verify()
        print(json.dumps(result, indent=2))
    finally:
        s.clean_up()
