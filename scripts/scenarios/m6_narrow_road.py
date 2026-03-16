"""
m6_narrow_road.py — Ego navigates a narrow Town02 street with 4 parked vehicles on both sides.

Criticality: MEDIUM
Map: Town02  (narrow urban streets)
Duration: 25 s

Determinism fix:
- 4 parked vehicles placed at fixed waypoint offsets on both sides of ego's route
- Parked vehicles: autopilot OFF, brake=1.0, hand_brake=True — will not move
- BasicAgent detects parked obstacles and steers around them
- All TLs green
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import carla
from scripts.scenarios.scenario_base import ScenarioBase, ScenarioFailed
from scripts.autonomous.agent_controller import AgentController
from scripts.data_collection.recorder import Recorder

DURATION   = 25.0
TARGET_KMH = 20.0

# (metres ahead, side offset in metres: positive = right, negative = left)
PARKED_CONFIG = [
    (20.0,  2.5),
    (40.0, -2.5),
    (60.0,  2.5),
    (80.0, -2.5),
]


def _dest(world, ego, dist_m=400.0):
    wp = world.get_map().get_waypoint(ego.get_location())
    wps = wp.next(dist_m)
    return wps[0].transform.location if wps \
        else world.get_map().get_spawn_points()[-1].location


class M6NarrowRoad(ScenarioBase):
    def __init__(self, **kwargs):
        super().__init__(map_name="Town02", spawn_index=0, **kwargs)

    def run(self, ap=None, rec=None) -> dict:
        self.world.set_weather(carla.WeatherParameters.CloudySunset)

        for tl in self.world.get_actors().filter("traffic.traffic_light"):
            tl.set_state(carla.TrafficLightState.Green)
            tl.freeze(True)

        bp_lib  = self.world.get_blueprint_library()
        car_bps = [b for b in bp_lib.filter("vehicle.*")
                   if b.get_attribute("number_of_wheels").as_int() == 4]
        park_bp = car_bps[0] if car_bps else bp_lib.filter("vehicle.*")[0]

        ego_wp = self.world.get_map().get_waypoint(self.ego.get_location())
        npcs = []
        for dist, side_m in PARKED_CONFIG:
            wps = ego_wp.next(dist)
            if not wps:
                continue
            fwd   = wps[0].transform.get_forward_vector()
            right = carla.Vector3D(x=-fwd.y, y=fwd.x, z=0.0)
            loc   = (
                wps[0].transform.location
                + carla.Location(x=right.x * side_m, y=right.y * side_m, z=0.3)
            )
            parked = self.world.try_spawn_actor(
                park_bp,
                carla.Transform(loc, wps[0].transform.rotation),
            )
            if parked:
                parked.apply_control(
                    carla.VehicleControl(brake=1.0, hand_brake=True)
                )
                npcs.append(parked)

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
            "map": "Town02",
            "duration_s": DURATION,
            "npc_count": len(npcs),
        }

    def verify(self) -> None:
        pass


if __name__ == "__main__":
    import json
    s = M6NarrowRoad(scenario_id="m6_narrow_road_test")
    s.setup()
    try:
        result = s.run(); s.verify()
        print(json.dumps(result, indent=2))
    finally:
        s.clean_up()
