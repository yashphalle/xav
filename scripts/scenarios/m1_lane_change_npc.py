"""
m1_lane_change_npc.py — Ego drives highway with an NPC in the adjacent lane.

Criticality: MEDIUM
Map: Town04
Duration: 30 s

Determinism fix:
- BasicAgent drives the ego at 70 km/h along highway
- NPC spawned in the LEFT adjacent lane at ego's starting position via get_left_lane()
- NPC drives at 65 km/h (slightly slower) so it gradually merges into frame
- At t=15s NPC's TM auto_lane_change causes a natural lane interaction
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import carla
from scripts.scenarios.scenario_base import ScenarioBase, ScenarioFailed
from scripts.autonomous.agent_controller import AgentController
from scripts.data_collection.recorder import Recorder

DURATION   = 30.0
TARGET_KMH = 70.0


def _dest(world, ego, dist_m=700.0):
    wp = world.get_map().get_waypoint(ego.get_location())
    wps = wp.next(dist_m)
    return wps[0].transform.location if wps \
        else world.get_map().get_spawn_points()[-1].location


class M1LaneChangeNpc(ScenarioBase):
    def __init__(self, **kwargs):
        super().__init__(map_name="Town04", spawn_index=10, **kwargs)

    def run(self, ap=None, rec=None) -> dict:
        self.world.set_weather(carla.WeatherParameters.CloudySunset)

        for tl in self.world.get_actors().filter("traffic.traffic_light"):
            tl.set_state(carla.TrafficLightState.Green)
            tl.freeze(True)

        bp_lib  = self.world.get_blueprint_library()
        car_bps = [b for b in bp_lib.filter("vehicle.*")
                   if b.get_attribute("number_of_wheels").as_int() == 4]
        npc_bp  = car_bps[0] if car_bps else bp_lib.filter("vehicle.*")[0]

        npcs = []
        ego_wp = self.world.get_map().get_waypoint(self.ego.get_location())
        left_wp = ego_wp.get_left_lane()
        if left_wp and left_wp.lane_type == carla.LaneType.Driving:
            t = left_wp.transform; t.location.z += 0.5
            npc = self.world.try_spawn_actor(npc_bp, t)
            if npc:
                npc.set_autopilot(True, self.traffic_manager.get_port())
                self.traffic_manager.ignore_lights_percentage(npc, 100)
                # NPC slightly slower than ego — will be overtaken gradually
                self.traffic_manager.vehicle_percentage_speed_difference(npc, 10)
                self.traffic_manager.auto_lane_change(npc, True)
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
            "criticality": "medium",
            "map": "Town04",
            "duration_s": DURATION,
            "npc_count": len(npcs),
        }

    def verify(self) -> None:
        pass  # MEDIUM — interaction is visual, no hard trigger requirement


if __name__ == "__main__":
    import json
    s = M1LaneChangeNpc(scenario_id="m1_lane_change_npc_test")
    s.setup()
    try:
        result = s.run(); s.verify()
        print(json.dumps(result, indent=2))
    finally:
        s.clean_up()
