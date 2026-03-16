"""
m6_narrow_road.py — Ego navigates a narrow road past two stationary parked vehicles

Criticality: MEDIUM
Map: Town02
Duration: 25s
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import carla
from scripts.scenarios.scenario_base import ScenarioBase
from scripts.autonomous.autopilot_controller import AutopilotController
from scripts.data_collection.recorder import Recorder


class M6NarrowRoad(ScenarioBase):
    def __init__(self, **kwargs):
        super().__init__(map_name="Town02", spawn_index=0, **kwargs)

    def run(self, ap=None, rec=None) -> dict:
        self.world.set_weather(carla.WeatherParameters.CloudySunset)

        npcs = []
        bp_lib = self.world.get_blueprint_library()
        spawn_points = self.world.get_map().get_spawn_points()

        # Spawn 2 parked vehicles as stationary obstacles
        parked_spawn_indices = [3, 4]
        npc_bps = [
            "vehicle.audi.a2",
            "vehicle.tesla.model3",
        ]
        for idx, sp_idx in enumerate(parked_spawn_indices):
            try:
                npc_bp = bp_lib.find(npc_bps[idx % len(npc_bps)])
                npc = self.world.try_spawn_actor(npc_bp, spawn_points[sp_idx])
                if npc is not None:
                    # Freeze the vehicle in place — full brake, no throttle
                    npc.apply_control(carla.VehicleControl(brake=1.0))
                    npcs.append(npc)
            except Exception:
                pass

        if ap is None:
            ap = AutopilotController(self.ego, self.traffic_manager, target_speed_kmh=20)
        ap.enable()

        if rec is None:
            rec = Recorder(self)
            rec.__enter__()
            _owns_rec = True
        else:
            _owns_rec = False

        DURATION = 25

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
            "map": "Town02",
            "duration_s": DURATION,
            "npc_count": len(npcs),
        }


if __name__ == "__main__":
    import json
    s = M6NarrowRoad(scenario_id="m6_narrow_road_test")
    s.setup()
    try:
        result = s.run()
        print(json.dumps(result, indent=2))
    finally:
        s.clean_up()
