"""
l1_highway_cruise.py — Ego cruises Town04 highway at 80 km/h with NPC traffic.

Criticality: LOW
Map: Town04  (ring-road highway, wide lanes)
Duration: 30 s

Determinism fix:
- BasicAgent follows a specific route (600 m ahead on same road)
- 5 NPC vehicles spawned via waypoints 40–180 m ahead in same lane
- All traffic lights frozen GREEN so BasicAgent never stops at a junction
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import carla
from scripts.scenarios.scenario_base import ScenarioBase, ScenarioFailed
from scripts.autonomous.agent_controller import AgentController
from scripts.data_collection.recorder import Recorder

DURATION       = 30.0
TARGET_KMH     = 80.0
NPC_SPACINGS_M = [40, 70, 100, 140, 180]


def _dest(world, ego, dist_m=600.0):
    wp = world.get_map().get_waypoint(ego.get_location())
    wps = wp.next(dist_m)
    return wps[0].transform.location if wps \
        else world.get_map().get_spawn_points()[-1].location


class L1HighwayCruise(ScenarioBase):
    def __init__(self, **kwargs):
        super().__init__(map_name="Town04", spawn_index=10, **kwargs)

    def run(self, ap=None, rec=None) -> dict:
        self.world.set_weather(carla.WeatherParameters.ClearNoon)

        # Freeze all TLs green — agent never stops at a junction
        for tl in self.world.get_actors().filter("traffic.traffic_light"):
            tl.set_state(carla.TrafficLightState.Green)
            tl.freeze(True)

        bp_lib  = self.world.get_blueprint_library()
        car_bps = [b for b in bp_lib.filter("vehicle.*")
                   if b.get_attribute("number_of_wheels").as_int() == 4]
        npc_bp  = car_bps[0] if car_bps else bp_lib.filter("vehicle.*")[0]

        ego_wp = self.world.get_map().get_waypoint(self.ego.get_location())
        npcs = []
        for dist in NPC_SPACINGS_M:
            wps = ego_wp.next(float(dist))
            if wps:
                t = wps[0].transform; t.location.z += 0.5
                npc = self.world.try_spawn_actor(npc_bp, t)
                if npc:
                    npc.set_autopilot(True, self.traffic_manager.get_port())
                    self.traffic_manager.ignore_lights_percentage(npc, 100)
                    self.traffic_manager.vehicle_percentage_speed_difference(npc, -20)
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
        pass  # LOW — no required trigger


if __name__ == "__main__":
    import json
    s = L1HighwayCruise(scenario_id="l1_highway_cruise_test")
    s.setup()
    try:
        result = s.run(); s.verify()
        print(json.dumps(result, indent=2))
    finally:
        s.clean_up()
