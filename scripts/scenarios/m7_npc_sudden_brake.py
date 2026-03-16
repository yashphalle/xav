"""
m7_npc_sudden_brake.py — NPC vehicle ahead executes a sudden hard brake at t=12s

Criticality: MEDIUM
Map: Town01
Duration: 25s
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import carla
from scripts.scenarios.scenario_base import ScenarioBase
from scripts.autonomous.autopilot_controller import AutopilotController
from scripts.data_collection.recorder import Recorder


class M7NpcSuddenBrake(ScenarioBase):
    def __init__(self, **kwargs):
        super().__init__(map_name="Town01", spawn_index=0, **kwargs)

    def run(self, ap=None, rec=None) -> dict:
        self.world.set_weather(carla.WeatherParameters.CloudySunset)

        npcs = []
        bp_lib = self.world.get_blueprint_library()
        spawn_points = self.world.get_map().get_spawn_points()

        # Spawn 1 NPC ahead of ego with a tight following distance to trigger braking
        npc = None
        try:
            npc_bp = bp_lib.find("vehicle.audi.a2")
            npc = self.world.try_spawn_actor(npc_bp, spawn_points[2])
            if npc is not None:
                npcs.append(npc)
        except Exception:
            pass

        if ap is None:
            ap = AutopilotController(self.ego, self.traffic_manager, target_speed_kmh=40)
        ap.enable()

        # Configure NPC with a close following distance to create a lead vehicle scenario
        if npc is not None and npc.is_alive:
            ap.configure_npc(npc, speed_pct_diff=0, distance_to_leading=4.0)

        if rec is None:
            rec = Recorder(self)
            rec.__enter__()
            _owns_rec = True
        else:
            _owns_rec = False

        DURATION = 25
        brake_triggered = False

        try:
            start = self.world.get_snapshot().timestamp.elapsed_seconds
            while True:
                frame = self.tick()
                ap.update(frame)
                rec.record(frame)

                elapsed = frame["timestamp"] - start

                # At t=12s, force the NPC to hard-brake for 20 ticks using ap.override()
                if not brake_triggered and elapsed >= 12.0 and npc is not None and npc.is_alive:
                    brake_triggered = True
                    with ap.override():
                        for _ in range(20):
                            npc.apply_control(carla.VehicleControl(brake=1.0))
                            inner_frame = self.tick()
                            ap.update(inner_frame)
                            rec.record(inner_frame)

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
            "map": "Town01",
            "duration_s": DURATION,
            "npc_count": len(npcs),
        }


if __name__ == "__main__":
    import json
    s = M7NpcSuddenBrake(scenario_id="m7_npc_sudden_brake_test")
    s.setup()
    try:
        result = s.run()
        print(json.dumps(result, indent=2))
    finally:
        s.clean_up()
