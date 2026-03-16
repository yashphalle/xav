"""
l5_overtake.py — Ego overtakes a slow-moving NPC vehicle on a highway stretch

Criticality: LOW
Map: Town04
Duration: 35s
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import carla
from scripts.scenarios.scenario_base import ScenarioBase
from scripts.autonomous.autopilot_controller import AutopilotController
from scripts.data_collection.recorder import Recorder


class L5Overtake(ScenarioBase):
    def __init__(self, **kwargs):
        super().__init__(map_name="Town04", spawn_index=10, **kwargs)

    def run(self, ap=None, rec=None) -> dict:
        # Set weather
        self.world.set_weather(carla.WeatherParameters.ClearNoon)

        # Spawn NPCs
        npcs = []
        bp_lib = self.world.get_blueprint_library()
        spawn_points = self.world.get_map().get_spawn_points()

        vehicle_bps = bp_lib.filter("vehicle.*")
        car_bps = [bp for bp in vehicle_bps if bp.get_attribute("number_of_wheels").as_int() == 4]

        # Spawn one slow NPC vehicle ahead of ego on the same road
        try:
            bp = car_bps[0]
            npc = self.world.try_spawn_actor(bp, spawn_points[12])
            if npc is not None:
                # Town04 limit is ~50 km/h; 60% speed_pct_diff results in ~20 km/h
                ap.configure_npc(npc, target_speed_kmh=20, speed_pct_diff=60, distance_to_leading=1.0)
                npcs.append(npc)
        except Exception:
            pass

        # Enable autopilot on ego at 60 km/h — faster than NPC to force overtake
        if ap is None:
            ap = AutopilotController(self.ego, self.traffic_manager, target_speed_kmh=60)
        ap.target_speed_kmh = 60
        ap._configure_tm()
        ap.enable()

        # Recording loop
        if rec is None:
            rec = Recorder(self)
            rec.__enter__()
            _owns_rec = True
        else:
            _owns_rec = False

        DURATION = 35

        try:
            start = self.world.get_snapshot().timestamp.elapsed_seconds
            while True:
                frame = self.tick()
                ap.update(frame)
                rec.record(frame)
                if frame["timestamp"] - start >= DURATION:
                    break
        finally:
            if _owns_rec:
                rec.__exit__(None, None, None)

        # Destroy NPCs
        for npc in npcs:
            if npc.is_alive:
                npc.destroy()

        ap.disable()
        return {
            "scenario_id": self.scenario_id,
            "criticality": "low",
            "map": "Town04",
            "duration_s": DURATION,
            "npc_count": len(npcs),
        }


if __name__ == "__main__":
    import json
    s = L5Overtake(scenario_id="l5_overtake_test")
    s.setup()
    try:
        result = s.run()
        print(json.dumps(result, indent=2))
    finally:
        s.clean_up()
