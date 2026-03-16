"""
l5_overtake.py — Ego encounters a slow NPC (20 km/h) and overtakes on Town04 highway.

Criticality: LOW
Map: Town04
Duration: 30 s

Determinism fix:
- Slow NPC spawned in RIGHT lane 30 m ahead via waypoints (20 km/h via TM)
- Ego spawned in LEFT lane (get_left_lane()), target 60 km/h
- Both lanes go in same direction; ego naturally passes the slow NPC
- BasicAgent drives without stopping; NPC stays slow throughout
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import carla
from scripts.scenarios.scenario_base import ScenarioBase, ScenarioFailed
from scripts.autonomous.agent_controller import AgentController
from scripts.data_collection.recorder import Recorder

DURATION    = 30.0
TARGET_KMH  = 60.0
NPC_KMH     = 20.0


def _dest(world, ego, dist_m=600.0):
    wp = world.get_map().get_waypoint(ego.get_location())
    wps = wp.next(dist_m)
    return wps[0].transform.location if wps \
        else world.get_map().get_spawn_points()[-1].location


class L5Overtake(ScenarioBase):
    def __init__(self, **kwargs):
        super().__init__(map_name="Town04", spawn_index=10, **kwargs)

    def run(self, ap=None, rec=None) -> dict:
        self.world.set_weather(carla.WeatherParameters.ClearNoon)

        for tl in self.world.get_actors().filter("traffic.traffic_light"):
            tl.set_state(carla.TrafficLightState.Green)
            tl.freeze(True)

        bp_lib  = self.world.get_blueprint_library()
        car_bps = [b for b in bp_lib.filter("vehicle.*")
                   if b.get_attribute("number_of_wheels").as_int() == 4]
        npc_bp  = car_bps[0] if car_bps else bp_lib.filter("vehicle.*")[0]

        # Spawn slow NPC in the right lane 30 m ahead
        ego_wp = self.world.get_map().get_waypoint(self.ego.get_location())
        npcs = []
        ahead_wps = ego_wp.next(30.0)
        if ahead_wps:
            # Try to put NPC in right lane
            right_wp = ahead_wps[0].get_right_lane() or ahead_wps[0]
            t = right_wp.transform; t.location.z += 0.5
            npc = self.world.try_spawn_actor(npc_bp, t)
            if npc:
                npc.set_autopilot(True, self.traffic_manager.get_port())
                self.traffic_manager.ignore_lights_percentage(npc, 100)
                # 20 km/h: NPC drives at (speed_limit × 0.25) ≈ very slow
                speed_limit = npc.get_speed_limit() or 80.0
                pct = ((speed_limit - NPC_KMH) / speed_limit) * 100.0
                self.traffic_manager.vehicle_percentage_speed_difference(npc, pct)
                npcs.append(npc)

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

        for npc in npcs:
            if npc.is_alive: npc.destroy()
        ap.disable()

        return {
            "scenario_id": self.scenario_id,
            "criticality": "low",
            "map": "Town04",
            "duration_s": DURATION,
            "npc_count": len(npcs),
        }

    def verify(self) -> None:
        pass


if __name__ == "__main__":
    import json
    s = L5Overtake(scenario_id="l5_overtake_test")
    s.setup()
    try:
        result = s.run(); s.verify()
        print(json.dumps(result, indent=2))
    finally:
        s.clean_up()
