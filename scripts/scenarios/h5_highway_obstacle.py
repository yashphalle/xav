"""
h5_highway_obstacle.py — Stationary NPC becomes highway obstacle; ego emergency-brakes.

Criticality: HIGH
Map: Town04
Duration: 25 s

Determinism guarantee:
1. All TLs frozen GREEN — ego drives at highway speed (80 km/h) unimpeded
2. NPC spawned 30 m ahead via waypoints (same lane/road as ego)
3. Phase 1 (t=5s): NPC stops hard (brake=1.0, hand_brake=True)
4. Phase 2 (t=8s or when ego > MIN_SPEED_KMH): ap.override() forces ego brake=0.9
   The 3 s gap gives NPC time to slow/stop before ego brakes
5. Speed gate ensures ego is at 50+ km/h when brake fires → large speed drop → BRAKING
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import carla
from scripts.scenarios.scenario_base import ScenarioBase, ScenarioFailed
from scripts.autonomous.agent_controller import AgentController
from scripts.data_collection.recorder import Recorder

DURATION       = 25.0
TARGET_KMH     = 80.0
MIN_SPEED_KMH  = 50.0
WARMUP_S       =  5.0
NPC_STOP_S     =  5.0   # when NPC stops
BRAKE_DELAY_S  =  3.0   # gap between NPC stop and forced ego brake
FALLBACK_S     = 16.0


def _dest(world, ego, dist_m=700.0):
    wp = world.get_map().get_waypoint(ego.get_location())
    wps = wp.next(dist_m)
    return wps[0].transform.location if wps \
        else world.get_map().get_spawn_points()[-1].location


class H5HighwayObstacle(ScenarioBase):
    def __init__(self, **kwargs):
        super().__init__(map_name="Town04", spawn_index=10, **kwargs)

    def run(self, ap=None, rec=None) -> dict:
        self.world.set_weather(carla.WeatherParameters.WetCloudyNoon)

        for tl in self.world.get_actors().filter("traffic.traffic_light"):
            tl.set_state(carla.TrafficLightState.Green)
            tl.freeze(True)

        bp_lib  = self.world.get_blueprint_library()
        car_bps = [b for b in bp_lib.filter("vehicle.*")
                   if b.get_attribute("number_of_wheels").as_int() == 4]
        npc_bp  = car_bps[0] if car_bps else bp_lib.filter("vehicle.*")[0]

        # Spawn NPC 30 m ahead in the same lane
        ego_wp    = self.world.get_map().get_waypoint(self.ego.get_location())
        ahead_wps = ego_wp.next(30.0)
        npc = None
        if ahead_wps:
            t = ahead_wps[0].transform; t.location.z += 0.5
            npc = self.world.try_spawn_actor(npc_bp, t)
        if npc:
            npc.set_autopilot(True, self.traffic_manager.get_port())
            self.traffic_manager.ignore_lights_percentage(npc, 100)
            self.traffic_manager.vehicle_percentage_speed_difference(npc, 0)

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

        npc_stopped        = False
        npc_stop_time      = None
        critical_triggered = False

        try:
            start = self.world.get_snapshot().timestamp.elapsed_seconds
            elapsed = 0.0
            while elapsed < DURATION:
                frame   = self.tick()
                ap.update(frame)
                rec.record(frame)
                elapsed = frame["timestamp"] - start

                # Phase 1: stop NPC after warmup
                if (not npc_stopped
                        and elapsed >= NPC_STOP_S
                        and npc and npc.is_alive):
                    npc_stopped   = True
                    npc_stop_time = elapsed
                    npc.set_autopilot(False)
                    npc.apply_control(
                        carla.VehicleControl(brake=1.0, hand_brake=True, throttle=0.0)
                    )

                # Phase 2: force ego brake 3 s after NPC stopped
                fire = (
                    not critical_triggered
                    and npc_stop_time is not None
                    and elapsed >= npc_stop_time + BRAKE_DELAY_S
                    and (frame["speed_kmh"] > MIN_SPEED_KMH or elapsed >= FALLBACK_S)
                )
                if fire:
                    critical_triggered = True
                    with ap.override():
                        for _ in range(40):   # 2 s
                            self.ego.apply_control(
                                carla.VehicleControl(brake=0.9, throttle=0.0)
                            )
                            frame   = self.tick()
                            ap.update(frame)
                            rec.record(frame)
                            elapsed = frame["timestamp"] - start

        finally:
            if _owns_rec:
                rec.__exit__(None, None, None)

        if npc and npc.is_alive: npc.destroy()
        ap.disable()

        return {
            "scenario_id": self.scenario_id,
            "criticality": "high",
            "map": "Town04",
            "duration_s": DURATION,
            "npc_count": 1 if npc else 0,
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
    s = H5HighwayObstacle(scenario_id="h5_highway_obstacle_test")
    s.setup()
    try:
        result = s.run()
        s.verify()
        print(json.dumps(result, indent=2))
    finally:
        s.clean_up()
