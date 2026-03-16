"""
h4_red_light.py — Ego approaches and hard-stops at a forced red light.

Criticality: HIGH
Map: Town03
Duration: 20s

Reliability fixes:
- Nearest traffic light to ego is forced RED via CARLA API at scenario start
- Red time set to 12s so the stop is long enough to capture on video
- Speed-gated fallback forced brake at FALLBACK_S in case TM deceleration
  is too gradual to cross the BRAKING threshold (need >5 km/h drop in 1s)
- After the stop, light is un-frozen so ego can continue
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import carla
from scripts.scenarios.scenario_base import ScenarioBase
from scripts.autonomous.autopilot_controller import AutopilotController
from scripts.data_collection.recorder import Recorder

DURATION      = 20.0
RED_HOLD_S    = 10.0   # seconds to hold traffic light red
WARMUP_S      =  3.0
FALLBACK_S    = 14.0   # forced brake if TM deceleration too gentle


class H4RedLight(ScenarioBase):
    def __init__(self, **kwargs):
        super().__init__(map_name="Town03", spawn_index=0, **kwargs)

    def run(self, ap=None, rec=None) -> dict:
        self.world.set_weather(carla.WeatherParameters.WetCloudyNoon)

        # --- Force nearest traffic light to RED ---
        ego_loc = self.ego.get_location()
        tl_actors = list(self.world.get_actors().filter("traffic.traffic_light"))
        forced_tl = None
        if tl_actors:
            forced_tl = min(tl_actors, key=lambda tl: tl.get_location().distance(ego_loc))
            forced_tl.set_state(carla.TrafficLightState.Red)
            forced_tl.set_red_time(RED_HOLD_S)

        if ap is None:
            ap = AutopilotController(self.ego, self.traffic_manager, target_speed_kmh=45)
        ap.enable()
        self.traffic_manager.ignore_lights_percentage(self.ego, 0)   # must obey lights

        if rec is None:
            rec = Recorder(self)
            rec.__enter__()
            _owns_rec = True
        else:
            _owns_rec = False

        braking_confirmed = False
        fallback_triggered = False

        try:
            start   = self.world.get_snapshot().timestamp.elapsed_seconds
            elapsed = 0.0

            while elapsed < DURATION:
                frame   = self.tick()
                ap.update(frame)
                rec.record(frame)
                elapsed = frame["timestamp"] - start

                # Mark when TM naturally brakes for the red light
                if not braking_confirmed and frame["brake"] > 0.5:
                    braking_confirmed = True

                # Fallback: if TM deceleration was too gradual (no BRAKING trigger
                # fired yet) and we're still moving, force a hard brake
                if (
                    not fallback_triggered
                    and elapsed >= FALLBACK_S
                    and frame["speed_kmh"] > 5.0
                ):
                    fallback_triggered = True
                    with ap.override():
                        for _ in range(30):
                            self.ego.apply_control(
                                carla.VehicleControl(brake=1.0, throttle=0.0)
                            )
                            frame   = self.tick()
                            ap.update(frame)
                            rec.record(frame)
                            elapsed = frame["timestamp"] - start

                # Un-freeze the light after hold time so ego can eventually move
                if elapsed >= RED_HOLD_S and forced_tl:
                    try:
                        forced_tl.set_state(carla.TrafficLightState.Green)
                        forced_tl.set_green_time(30.0)
                        forced_tl = None   # only do this once
                    except Exception:
                        forced_tl = None
        finally:
            if _owns_rec:
                rec.__exit__(None, None, None)

        ap.disable()

        return {
            "scenario_id": self.scenario_id,
            "criticality": "high",
            "map": "Town03",
            "duration_s": DURATION,
            "npc_count": 0,
        }


if __name__ == "__main__":
    import json
    s = H4RedLight(scenario_id="h4_red_light_test")
    s.setup()
    try:
        result = s.run()
        print(json.dumps(result, indent=2))
    finally:
        s.clean_up()
