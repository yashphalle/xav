"""
m7_npc_sudden_brake.py — NPC vehicle 15 m ahead suddenly hard-brakes at t=10s.

Criticality: MEDIUM
Map: Town01
Duration: 25 s

Determinism fix:
- BasicAgent drives ego at 40 km/h
- NPC spawned 15 m ahead in same lane via waypoints, TM autopilot at 40 km/h
- At t=10s: NPC.set_autopilot(False) + apply_control(brake=1.0, hand_brake=True)
- BasicAgent detects stopped vehicle and brakes naturally (BRAKING trigger expected)
- No forced override needed — BasicAgent's vehicle detection handles this
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import carla
from scripts.scenarios.scenario_base import ScenarioBase, ScenarioFailed
from scripts.autonomous.agent_controller import AgentController
from scripts.data_collection.recorder import Recorder

DURATION      = 25.0
TARGET_KMH    = 40.0
NPC_BRAKE_S   = 10.0
WARMUP_S      = 3.0


def _dest(world, ego, dist_m=500.0):
    wp = world.get_map().get_waypoint(ego.get_location())
    wps = wp.next(dist_m)
    return wps[0].transform.location if wps \
        else world.get_map().get_spawn_points()[-1].location


class M7NpcSuddenBrake(ScenarioBase):
    def __init__(self, **kwargs):
        super().__init__(map_name="Town01", spawn_index=0, **kwargs)

    def run(self, ap=None, rec=None) -> dict:
        self.world.set_weather(carla.WeatherParameters.CloudySunset)

        for tl in self.world.get_actors().filter("traffic.traffic_light"):
            tl.set_state(carla.TrafficLightState.Green)
            tl.freeze(True)

        bp_lib  = self.world.get_blueprint_library()
        car_bps = [b for b in bp_lib.filter("vehicle.*")
                   if b.get_attribute("number_of_wheels").as_int() == 4]
        npc_bp  = car_bps[0] if car_bps else bp_lib.filter("vehicle.*")[0]

        ego_wp    = self.world.get_map().get_waypoint(self.ego.get_location())
        ahead_wps = ego_wp.next(15.0)
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

        npc_braked = False

        try:
            start = self.world.get_snapshot().timestamp.elapsed_seconds
            elapsed = 0.0
            while elapsed < DURATION:
                frame   = self.tick()
                ap.update(frame)
                rec.record(frame)
                elapsed = frame["timestamp"] - start

                if not npc_braked and elapsed >= NPC_BRAKE_S:
                    npc_braked = True
                    if npc and npc.is_alive:
                        npc.set_autopilot(False)
                        npc.apply_control(
                            carla.VehicleControl(brake=1.0, hand_brake=True, throttle=0.0)
                        )

        finally:
            if _owns_rec:
                rec.__exit__(None, None, None)

        if npc and npc.is_alive: npc.destroy()
        ap.disable()

        return {
            "scenario_id": self.scenario_id,
            "criticality": "medium",
            "map": "Town01",
            "duration_s": DURATION,
            "npc_count": 1 if npc else 0,
        }

    def verify(self) -> None:
        pass


if __name__ == "__main__":
    import json
    s = M7NpcSuddenBrake(scenario_id="m7_npc_sudden_brake_test")
    s.setup()
    try:
        result = s.run(); s.verify()
        print(json.dumps(result, indent=2))
    finally:
        s.clean_up()
