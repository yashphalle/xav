"""
h2_npc_cutoff.py — NPC vehicle suddenly brakes causing a near-rear-end collision on highway

Criticality: HIGH
Map: Town04
Duration: 25s
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import carla
from scripts.scenarios.scenario_base import ScenarioBase
from scripts.autonomous.autopilot_controller import AutopilotController
from scripts.data_collection.recorder import Recorder


class H2NpcCutoff(ScenarioBase):
    def __init__(self, **kwargs):
        super().__init__(map_name="Town04", spawn_index=10, **kwargs)

    def run(self, ap=None, rec=None) -> dict:
        self.world.set_weather(carla.WeatherParameters.WetCloudyNoon)

        npcs = []
        bp_lib = self.world.get_blueprint_library()
        spawn_points = self.world.get_map().get_spawn_points()

        # Spawn NPC vehicle ahead of ego on highway
        vehicle_bps = bp_lib.filter("vehicle.*")
        npc_bp = vehicle_bps[0]
        npc = self.world.try_spawn_actor(npc_bp, spawn_points[11])
        if npc:
            npcs.append(npc)
            npc.set_autopilot(True, self.traffic_manager.get_port())
            ap_tmp = AutopilotController(self.ego, self.traffic_manager, target_speed_kmh=80)
            ap_tmp.configure_npc(npc, speed_pct_diff=-20, distance_to_leading=1.0)

        if ap is None:
            ap = AutopilotController(self.ego, self.traffic_manager, target_speed_kmh=80)
        ap.enable()

        if rec is None:
            rec = Recorder(self)
            rec.__enter__()
            _owns_rec = True
        else:
            _owns_rec = False

        critical_triggered = False

        try:
            start = self.world.get_snapshot().timestamp.elapsed_seconds
            elapsed = 0.0
            while elapsed < 25:
                frame = self.tick()
                ap.update(frame)
                rec.record(frame)
                elapsed = frame["timestamp"] - start

                # At t=10s: NPC suddenly brakes, ego performs emergency brake
                if elapsed >= 10.0 and not critical_triggered:
                    critical_triggered = True
                    # Force NPC to sudden stop
                    if npc and npc.is_alive:
                        npc.set_autopilot(False)
                        npc.apply_control(carla.VehicleControl(brake=1.0, hand_brake=True))
                    # Force ego emergency brake
                    with ap.override():
                        for _ in range(40):  # ~2s at 20Hz
                            self.ego.apply_control(carla.VehicleControl(brake=1.0, throttle=0.0))
                            frame = self.tick()
                            ap.update(frame)
                            rec.record(frame)
        finally:
            if _owns_rec:
                rec.__exit__(None, None, None)

        for npc in npcs:
            if npc.is_alive:
                npc.destroy()
        ap.disable()

        return {
            "scenario_id": self.scenario_id,
            "criticality": "high",
            "map": "Town04",
            "duration_s": 25,
            "npc_count": len(npcs),
        }


if __name__ == "__main__":
    import json
    s = H2NpcCutoff(scenario_id="h2_npc_cutoff_test")
    s.setup()
    try:
        result = s.run()
        print(json.dumps(result, indent=2))
    finally:
        s.clean_up()
