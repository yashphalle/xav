"""
m4_yellow_light.py — Ego approaches an intersection; light turns YELLOW at t=8s.

Criticality: MEDIUM
Map: Town03
Duration: 25 s

Determinism fix:
- All TLs start GREEN so BasicAgent approaches intersection at full speed
- At t=8s: find nearest TL to ego and set YELLOW (2s) then RED
- BasicAgent detects RED and brakes naturally (no forced override)
- This produces a natural BRAKING trigger without scripted intervention
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
TL_CHANGE_S   = 8.0    # seconds until light turns yellow/red
WARMUP_S      = 3.0


def _dest(world, ego, dist_m=500.0):
    wp = world.get_map().get_waypoint(ego.get_location())
    wps = wp.next(dist_m)
    return wps[0].transform.location if wps \
        else world.get_map().get_spawn_points()[-1].location


class M4YellowLight(ScenarioBase):
    def __init__(self, **kwargs):
        super().__init__(map_name="Town03", spawn_index=0, **kwargs)

    def run(self, ap=None, rec=None) -> dict:
        self.world.set_weather(carla.WeatherParameters.CloudySunset)

        tl_actors = list(self.world.get_actors().filter("traffic.traffic_light"))
        # Start all green
        for tl in tl_actors:
            tl.set_state(carla.TrafficLightState.Green)
            tl.freeze(True)

        if ap is None:
            ap = AgentController(self.ego, self.world,
                                 target_speed_kmh=TARGET_KMH,
                                 ignore_traffic_lights=False)  # obey lights
            ap.set_destination(_dest(self.world, self.ego))
        ap.enable()

        if rec is None:
            rec = Recorder(self); rec.__enter__(); _owns_rec = True
        else:
            _owns_rec = False

        tl_changed   = False
        target_tl    = None

        try:
            start = self.world.get_snapshot().timestamp.elapsed_seconds
            elapsed = 0.0
            while elapsed < DURATION:
                frame   = self.tick()
                ap.update(frame)
                rec.record(frame)
                elapsed = frame["timestamp"] - start

                # At TL_CHANGE_S find the nearest TL to ego and set YELLOW → RED
                if not tl_changed and elapsed >= TL_CHANGE_S:
                    tl_changed = True
                    ego_loc = self.ego.get_location()
                    if tl_actors:
                        target_tl = min(
                            tl_actors,
                            key=lambda tl: tl.get_location().distance(ego_loc),
                        )
                        # Unfreeze so we can change state
                        target_tl.freeze(False)
                        target_tl.set_state(carla.TrafficLightState.Yellow)
                        target_tl.set_yellow_time(2.0)
                        target_tl.set_red_time(10.0)
                        # The light will cycle Yellow→Red automatically now

        finally:
            if _owns_rec:
                rec.__exit__(None, None, None)

        ap.disable()

        return {
            "scenario_id": self.scenario_id,
            "criticality": "medium",
            "map": "Town03",
            "duration_s": DURATION,
            "npc_count": 0,
        }

    def verify(self) -> None:
        pass


if __name__ == "__main__":
    import json
    s = M4YellowLight(scenario_id="m4_yellow_light_test")
    s.setup()
    try:
        result = s.run(); s.verify()
        print(json.dumps(result, indent=2))
    finally:
        s.clean_up()
