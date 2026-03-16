"""
h4_red_light.py — Ego approaches intersection; light turns RED; ego emergency-brakes.

Criticality: HIGH
Map: Town03
Duration: 20 s

Determinism guarantee:
1. All TLs start GREEN and frozen — ego approaches intersection at full speed
2. At t=8s: find nearest TL to ego, unfreeze it, set RED (hold 10 s)
3. ap.override() forces ego brake=1.0 for 2 s simultaneously to guarantee BRAKING
4. After RED hold, set TL GREEN so ego can continue
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import carla
from scripts.scenarios.scenario_base import ScenarioBase, ScenarioFailed
from scripts.autonomous.agent_controller import AgentController
from scripts.data_collection.recorder import Recorder

DURATION      = 20.0
TARGET_KMH    = 40.0
MIN_SPEED_KMH = 15.0
TL_TRIGGER_S  =  8.0
RED_HOLD_S    = 10.0
WARMUP_S      =  3.0
FALLBACK_S    = 13.0


def _dest(world, ego, dist_m=500.0):
    wp = world.get_map().get_waypoint(ego.get_location())
    wps = wp.next(dist_m)
    return wps[0].transform.location if wps \
        else world.get_map().get_spawn_points()[-1].location


class H4RedLight(ScenarioBase):
    def __init__(self, **kwargs):
        super().__init__(map_name="Town03", spawn_index=0, **kwargs)

    def run(self, ap=None, rec=None) -> dict:
        self.world.set_weather(carla.WeatherParameters.WetCloudyNoon)

        tl_actors = list(self.world.get_actors().filter("traffic.traffic_light"))
        # Start all green (ego approaches at speed)
        for tl in tl_actors:
            tl.set_state(carla.TrafficLightState.Green)
            tl.freeze(True)

        if ap is None:
            ap = AgentController(self.ego, self.world,
                                 target_speed_kmh=TARGET_KMH,
                                 ignore_traffic_lights=True)  # we control TL manually
            ap.set_destination(_dest(self.world, self.ego))
        ap.enable()

        if rec is None:
            rec = Recorder(self); rec.__enter__(); _owns_rec = True
        else:
            _owns_rec = False

        critical_triggered = False
        tl_set_red         = False
        forced_tl          = None

        try:
            start = self.world.get_snapshot().timestamp.elapsed_seconds
            elapsed = 0.0
            while elapsed < DURATION:
                frame   = self.tick()
                ap.update(frame)
                rec.record(frame)
                elapsed = frame["timestamp"] - start

                # At TL_TRIGGER_S set nearest TL to RED
                if not tl_set_red and elapsed >= TL_TRIGGER_S:
                    tl_set_red = True
                    ego_loc = self.ego.get_location()
                    if tl_actors:
                        forced_tl = min(
                            tl_actors,
                            key=lambda tl: tl.get_location().distance(ego_loc),
                        )
                        forced_tl.freeze(False)
                        forced_tl.set_state(carla.TrafficLightState.Red)
                        forced_tl.set_red_time(RED_HOLD_S)

                # Force ego brake when moving (speed-gated + fallback)
                fire = (
                    not critical_triggered
                    and elapsed >= TL_TRIGGER_S
                    and (frame["speed_kmh"] > MIN_SPEED_KMH or elapsed >= FALLBACK_S)
                )
                if fire:
                    critical_triggered = True
                    with ap.override():
                        for _ in range(40):   # 2 s
                            self.ego.apply_control(
                                carla.VehicleControl(brake=1.0, throttle=0.0)
                            )
                            frame   = self.tick()
                            ap.update(frame)
                            rec.record(frame)
                            elapsed = frame["timestamp"] - start

                # Unfreeze TL to green after hold so ego can continue
                if forced_tl and elapsed >= TL_TRIGGER_S + RED_HOLD_S:
                    try:
                        forced_tl.set_state(carla.TrafficLightState.Green)
                        forced_tl.freeze(True)
                        forced_tl = None
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

    def verify(self) -> None:
        braking = [e for e in self._action_events
                   if e["trigger_type"] == "BRAKING"]
        if not braking:
            raise ScenarioFailed(
                f"{self.scenario_id}: expected BRAKING trigger. "
                f"Got: {[e['trigger_type'] for e in self._action_events]}"
            )


if __name__ == "__main__":
    import json
    s = H4RedLight(scenario_id="h4_red_light_test")
    s.setup()
    try:
        result = s.run()
        s.verify()
        print(json.dumps(result, indent=2))
    finally:
        s.clean_up()
