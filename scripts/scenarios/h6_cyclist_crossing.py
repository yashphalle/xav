"""
h6_cyclist_crossing.py — Cyclist crosses intersection, ego yields with emergency brake.

Criticality: HIGH
Map: Town03
Duration: 20s
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import carla
from scripts.scenarios.scenario_base import ScenarioBase
from scripts.autonomous.autopilot_controller import AutopilotController
from scripts.data_collection.recorder import Recorder

DURATION      = 20.0
CRITICAL_TIME =  8.0   # seconds into run when ego brakes to yield to cyclist


class H6CyclistCrossing(ScenarioBase):
    """
    Ego approaches an intersection at 35 km/h. A cyclist crosses the road.
    At t=8s the ego performs a forced emergency brake to yield.
    """

    def __init__(self, **kwargs):
        super().__init__(map_name="Town03", spawn_index=2, **kwargs)

    def run(self, ap=None, rec=None) -> dict:
        self.world.set_weather(carla.WeatherParameters.WetCloudyNoon)

        npcs = []
        bp_lib       = self.world.get_blueprint_library()
        spawn_points = self.world.get_map().get_spawn_points()

        # --- Spawn cyclist (slow bicycle NPC) ---
        cyclist_bp = None
        for name in ("vehicle.gazelle.omafiets", "vehicle.bh.crossbike", "vehicle.diamondback.century"):
            try:
                cyclist_bp = bp_lib.find(name)
                break
            except IndexError:
                continue

        if cyclist_bp is None:
            candidates = bp_lib.filter("vehicle.*")
            cyclist_bp = next(
                (b for b in candidates if any(k in b.id for k in ("bike", "cycle", "cross"))),
                candidates[0],
            )

        if len(spawn_points) > 5:
            cyclist_transform = carla.Transform(
                spawn_points[5].location + carla.Location(x=0, y=8, z=0.3),
                carla.Rotation(yaw=spawn_points[5].rotation.yaw + 90),
            )
            cyclist = self.world.try_spawn_actor(cyclist_bp, cyclist_transform)
            if cyclist:
                npcs.append(cyclist)
                cyclist.set_autopilot(True, self.traffic_manager.get_port())
                self.traffic_manager.vehicle_percentage_speed_difference(cyclist, 80)
                self.traffic_manager.ignore_lights_percentage(cyclist, 100)

        # --- Ego autopilot ---
        if ap is None:
            ap = AutopilotController(self.ego, self.traffic_manager, target_speed_kmh=35)
        ap.enable()

        # --- Recording loop ---
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

                if elapsed >= CRITICAL_TIME and not critical_triggered:
                    critical_triggered = True
                    with ap.override():
                        for _ in range(25):
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
            "map": "Town03",
            "duration_s": DURATION,
            "npc_count": len(npcs),
        }


if __name__ == "__main__":
    import json
    s = H6CyclistCrossing(scenario_id="h6_cyclist_crossing_test")
    s.setup()
    try:
        result = s.run()
        print(json.dumps(result, indent=2))
    finally:
        s.clean_up()
