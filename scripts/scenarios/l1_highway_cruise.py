"""
l1_highway_cruise.py — Ego cruises on a multi-lane highway surrounded by NPC traffic

Criticality: LOW
Map: Town04
Duration: 30s
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import carla
from scripts.scenarios.scenario_base import ScenarioBase
from scripts.autonomous.autopilot_controller import AutopilotController
from scripts.data_collection.recorder import Recorder


class L1HighwayCruise(ScenarioBase):
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
        npc_spawn_indices = [15, 20, 25, 30, 35]

        for i, sp_idx in enumerate(npc_spawn_indices):
            try:
                bp = car_bps[i % len(car_bps)]
                npc = self.world.try_spawn_actor(bp, spawn_points[sp_idx])
                if npc is not None:
                    ap.configure_npc(npc, target_speed_kmh=80, speed_pct_diff=0)
                    npcs.append(npc)
            except Exception:
                pass

        # Enable autopilot on ego
        if ap is None:
            ap = AutopilotController(self.ego, self.traffic_manager, target_speed_kmh=80)
        ap.target_speed_kmh = 80
        ap._configure_tm()
        ap.enable()

        # Recording loop
        if rec is None:
            rec = Recorder(self)
            rec.__enter__()
            _owns_rec = True
        else:
            _owns_rec = False

        DURATION = 30

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
    s = L1HighwayCruise(scenario_id="l1_highway_cruise_test")
    s.setup()
    try:
        result = s.run()
        print(json.dumps(result, indent=2))
    finally:
        s.clean_up()
