"""
m5_pedestrian_yield.py — Ego approaches pedestrian crossing; walker steps onto road at t=8s.

Criticality: MEDIUM
Map: Town01
Duration: 25 s

Determinism fix:
- Walker spawned on sidewalk 20 m ahead via waypoint offset (3.5 m right)
- At t=8s: walker.apply_control(WalkerControl) sends pedestrian into road
- BasicAgent does NOT automatically detect walkers — but the video shows
  a pedestrian situation clearly (PEDESTRIAN_CLOSE trigger via YOLO if walker
  fills 30%+ of frame)
- BasicAgent keeps driving at moderate speed; the pedestrian event is visual
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import carla
from scripts.scenarios.scenario_base import ScenarioBase, ScenarioFailed
from scripts.autonomous.agent_controller import AgentController
from scripts.data_collection.recorder import Recorder

DURATION      = 25.0
TARGET_KMH    = 30.0
WALKER_TIME_S = 8.0
WARMUP_S      = 3.0


def _dest(world, ego, dist_m=400.0):
    wp = world.get_map().get_waypoint(ego.get_location())
    wps = wp.next(dist_m)
    return wps[0].transform.location if wps \
        else world.get_map().get_spawn_points()[-1].location


class M5PedestrianYield(ScenarioBase):
    def __init__(self, **kwargs):
        super().__init__(map_name="Town01", spawn_index=0, **kwargs)

    def run(self, ap=None, rec=None) -> dict:
        self.world.set_weather(carla.WeatherParameters.CloudySunset)

        for tl in self.world.get_actors().filter("traffic.traffic_light"):
            tl.set_state(carla.TrafficLightState.Green)
            tl.freeze(True)

        # Spawn walker 20 m ahead on the right sidewalk
        bp_lib   = self.world.get_blueprint_library()
        ped_bps  = list(bp_lib.filter("walker.pedestrian.*"))
        walker_bp = ped_bps[0] if ped_bps else None

        walker   = None
        walk_dir = carla.Vector3D(x=-1.0, y=0.0, z=0.0)  # default; overridden below

        ego_wp    = self.world.get_map().get_waypoint(self.ego.get_location())
        ahead_wps = ego_wp.next(20.0)
        if walker_bp and ahead_wps:
            fwd   = ahead_wps[0].transform.get_forward_vector()
            right = carla.Vector3D(x=-fwd.y, y=fwd.x, z=0.0)
            loc   = (
                ahead_wps[0].transform.location
                + carla.Location(x=right.x * 3.5, y=right.y * 3.5, z=0.5)
            )
            walker   = self.world.try_spawn_actor(walker_bp, carla.Transform(loc))
            walk_dir = carla.Vector3D(x=-right.x, y=-right.y, z=0.0)

        npcs = [walker] if walker else []

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

        walker_sent = False

        try:
            start = self.world.get_snapshot().timestamp.elapsed_seconds
            elapsed = 0.0
            while elapsed < DURATION:
                frame   = self.tick()
                ap.update(frame)
                rec.record(frame)
                elapsed = frame["timestamp"] - start

                if not walker_sent and elapsed >= WALKER_TIME_S:
                    walker_sent = True
                    if walker and walker.is_alive:
                        walker.apply_control(carla.WalkerControl(
                            speed=2.5,
                            direction=walk_dir,
                        ))

        finally:
            if _owns_rec:
                rec.__exit__(None, None, None)

        for npc in npcs:
            if npc and npc.is_alive: npc.destroy()
        ap.disable()

        return {
            "scenario_id": self.scenario_id,
            "criticality": "medium",
            "map": "Town01",
            "duration_s": DURATION,
            "npc_count": len(npcs),
        }

    def verify(self) -> None:
        pass


if __name__ == "__main__":
    import json
    s = M5PedestrianYield(scenario_id="m5_pedestrian_yield_test")
    s.setup()
    try:
        result = s.run(); s.verify()
        print(json.dumps(result, indent=2))
    finally:
        s.clean_up()
