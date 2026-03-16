"""
h2_npc_cutoff.py — NPC brakes suddenly on highway; ego emergency brakes.

Criticality: HIGH
Map: Town04
Duration: 25s

Reliability fixes:
- NPC spawned 25m ahead of ego using waypoints (guaranteed same lane/road)
- Critical event fires when ego speed > MIN_SPEED_KMH, not at fixed time
- Fallback at FALLBACK_S
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import carla
from scripts.scenarios.scenario_base import ScenarioBase
from scripts.autonomous.autopilot_controller import AutopilotController
from scripts.data_collection.recorder import Recorder

DURATION      = 25.0
MIN_SPEED_KMH = 40.0
WARMUP_S      =  5.0
FALLBACK_S    = 14.0


class H2NpcCutoff(ScenarioBase):
    def __init__(self, **kwargs):
        super().__init__(map_name="Town04", spawn_index=10, **kwargs)

    def run(self, ap=None, rec=None) -> dict:
        self.world.set_weather(carla.WeatherParameters.WetCloudyNoon)

        npcs = []
        bp_lib     = self.world.get_blueprint_library()
        car_bps    = [b for b in bp_lib.filter("vehicle.*") if b.get_attribute("number_of_wheels").as_int() == 4]
        npc_bp     = car_bps[0] if car_bps else bp_lib.filter("vehicle.*")[0]

        # Spawn NPC 25m ahead in the same lane using waypoints
        ego_wp    = self.world.get_map().get_waypoint(self.ego.get_location())
        ahead_wps = ego_wp.next(25.0)
        npc       = None

        if ahead_wps:
            npc_transform = ahead_wps[0].transform
            npc_transform.location.z += 0.5
            npc = self.world.try_spawn_actor(npc_bp, npc_transform)

        if npc:
            npcs.append(npc)
            npc.set_autopilot(True, self.traffic_manager.get_port())
            self.traffic_manager.vehicle_percentage_speed_difference(npc, 0)
            self.traffic_manager.distance_to_leading_vehicle(npc, 2.0)

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
            start   = self.world.get_snapshot().timestamp.elapsed_seconds
            elapsed = 0.0

            while elapsed < DURATION:
                frame   = self.tick()
                ap.update(frame)
                rec.record(frame)
                elapsed = frame["timestamp"] - start

                fire = (
                    not critical_triggered
                    and elapsed >= WARMUP_S
                    and (frame["speed_kmh"] > MIN_SPEED_KMH or elapsed >= FALLBACK_S)
                )

                if fire:
                    critical_triggered = True

                    # NPC sudden hard stop
                    if npc and npc.is_alive:
                        npc.set_autopilot(False)
                        npc.apply_control(carla.VehicleControl(brake=1.0, hand_brake=True))

                    # Forced ego emergency brake
                    with ap.override():
                        for _ in range(40):   # ~2 s
                            self.ego.apply_control(
                                carla.VehicleControl(brake=1.0, throttle=0.0)
                            )
                            frame   = self.tick()
                            ap.update(frame)
                            rec.record(frame)
                            elapsed = frame["timestamp"] - start
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
            "duration_s": DURATION,
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
