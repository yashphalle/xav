"""
m3_roundabout_traffic.py — Ego enters a roundabout; 3 NPC vehicles already circulating.

Criticality: MEDIUM
Map: Town03
Duration: 30 s

Determinism fix:
- Ego at spawn_index=7 (before Town03 roundabout); destination on far side
- 3 NPCs spawned at roundabout entry waypoints 80/120/160 m ahead so they
  circulate inside the roundabout when ego arrives
- BasicAgent slows/stops naturally when NPCs block entry
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import carla
from scripts.scenarios.scenario_base import ScenarioBase, ScenarioFailed
from scripts.autonomous.agent_controller import AgentController
from scripts.data_collection.recorder import Recorder

DURATION   = 30.0
TARGET_KMH = 25.0


class M3RoundaboutTraffic(ScenarioBase):
    def __init__(self, **kwargs):
        super().__init__(map_name="Town03", spawn_index=7, **kwargs)

    def run(self, ap=None, rec=None) -> dict:
        self.world.set_weather(carla.WeatherParameters.CloudySunset)

        for tl in self.world.get_actors().filter("traffic.traffic_light"):
            tl.set_state(carla.TrafficLightState.Green)
            tl.freeze(True)

        bp_lib  = self.world.get_blueprint_library()
        car_bps = [b for b in bp_lib.filter("vehicle.*")
                   if b.get_attribute("number_of_wheels").as_int() == 4]
        npc_bp  = car_bps[0] if car_bps else bp_lib.filter("vehicle.*")[0]

        ego_wp = self.world.get_map().get_waypoint(self.ego.get_location())
        npcs = []
        for dist in [80, 120, 160]:
            wps = ego_wp.next(float(dist))
            if wps:
                t = wps[0].transform; t.location.z += 0.5
                npc = self.world.try_spawn_actor(npc_bp, t)
                if npc:
                    npc.set_autopilot(True, self.traffic_manager.get_port())
                    self.traffic_manager.ignore_lights_percentage(npc, 100)
                    self.traffic_manager.vehicle_percentage_speed_difference(npc, 0)
                    npcs.append(npc)

        spawn_points = self.world.get_map().get_spawn_points()
        dest_idx = min(75, len(spawn_points) - 1)
        dest = spawn_points[dest_idx].location

        if ap is None:
            ap = AgentController(self.ego, self.world,
                                 target_speed_kmh=TARGET_KMH,
                                 ignore_traffic_lights=True)
            ap.set_destination(dest)
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
            "map": "Town03",
            "duration_s": DURATION,
            "npc_count": len(npcs),
        }

    def verify(self) -> None:
        pass


if __name__ == "__main__":
    import json
    s = M3RoundaboutTraffic(scenario_id="m3_roundabout_traffic_test")
    s.setup()
    try:
        result = s.run(); s.verify()
        print(json.dumps(result, indent=2))
    finally:
        s.clean_up()
