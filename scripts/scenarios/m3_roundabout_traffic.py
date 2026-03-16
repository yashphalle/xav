"""
m3_roundabout_traffic.py — Ego navigates a roundabout with circulating NPC vehicles

Criticality: MEDIUM
Map: Town03
Duration: 35s
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import carla
from scripts.scenarios.scenario_base import ScenarioBase
from scripts.autonomous.autopilot_controller import AutopilotController
from scripts.data_collection.recorder import Recorder


class M3RoundaboutTraffic(ScenarioBase):
    def __init__(self, **kwargs):
        super().__init__(map_name="Town03", spawn_index=1, **kwargs)

    def run(self, ap=None, rec=None) -> dict:
        self.world.set_weather(carla.WeatherParameters.CloudySunset)

        npcs = []
        bp_lib = self.world.get_blueprint_library()
        spawn_points = self.world.get_map().get_spawn_points()

        # Spawn 3 NPC vehicles circulating in/around the roundabout
        npc_spawn_indices = [2, 3, 4]
        npc_bps = [
            "vehicle.audi.a2",
            "vehicle.tesla.model3",
            "vehicle.nissan.patrol",
        ]
        for idx, sp_idx in enumerate(npc_spawn_indices):
            try:
                npc_bp = bp_lib.find(npc_bps[idx % len(npc_bps)])
                npc = self.world.try_spawn_actor(npc_bp, spawn_points[sp_idx])
                if npc is not None:
                    npcs.append(npc)
            except Exception:
                pass

        if ap is None:
            ap = AutopilotController(self.ego, self.traffic_manager, target_speed_kmh=25)
        ap.enable()

        # Configure NPCs after ap is ready
        for npc in npcs:
            ap.configure_npc(npc, speed_pct_diff=0)

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

        for npc in npcs:
            if npc.is_alive:
                npc.destroy()
        ap.disable()

        return {
            "scenario_id": self.scenario_id,
            "criticality": "medium",
            "map": "Town03",
            "duration_s": DURATION,
            "npc_count": len(npcs),
        }


if __name__ == "__main__":
    import json
    s = M3RoundaboutTraffic(scenario_id="m3_roundabout_traffic_test")
    s.setup()
    try:
        result = s.run()
        print(json.dumps(result, indent=2))
    finally:
        s.clean_up()
