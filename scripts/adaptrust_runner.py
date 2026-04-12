"""
adaptrust_runner.py
Core runner: sets up CarlaDataProvider, spawns ego, attaches sensors,
instantiates an AdaptTrust scenario, and runs the combined tick loop.

Tick loop per simulation step:
  1. world.tick()                    — advance physics
  2. CarlaDataProvider.on_carla_tick() — refresh actor location/velocity cache
  3. build_telemetry(snapshot, ego)   — assemble frame dict
  4. rec.record(frame)                — log to CSV/JSON
  5. scenario.scenario_tree.tick_once() — advance behavior tree

Usage (called from run_adaptrust.py, not directly):
  runner = AdaptTrustRunner(scenario_id="H1_PedestrianDart", run_id=1)
  runner.run()
"""

import sys
import time
import math
import json
from pathlib import Path

import py_trees

# ---- project paths --------------------------------------------------------
_ROOT = Path(__file__).resolve().parents[1]
_HOME = Path.home()
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_HOME / "scenario_runner"))
sys.path.insert(0, str(_HOME / "carla/PythonAPI/carla"))
sys.path.insert(0, str(_HOME / "carla/PythonAPI/carla/agents"))

import carla
from srunner.scenariomanager.carla_data_provider import CarlaDataProvider
from srunner.scenariomanager.timer import GameTime
from scripts.scenarios.adaptrust_scenarios import (
    SCENARIO_REGISTRY, SCENARIO_MAP, AdaptTrustConfig,
)
from scripts.data_collection.recorder import Recorder
from scripts.explanation_gen.generator import generate_all_explanations
from scripts.video_pipeline.overlay import render_overlays


# ---------------------------------------------------------------------------
# Sensor helpers
# ---------------------------------------------------------------------------

class SensorBundle:
    """Attaches RGB camera, optional rear camera, and LiDAR to ego."""

    def __init__(self, world, ego, ctx, output_dir: Path, enable_rear: bool = False):
        self._ctx = ctx
        output_dir.mkdir(parents=True, exist_ok=True)

        bp_lib = world.get_blueprint_library()

        # RGB camera — matches ScenarioBase resolution (1920×1080)
        cam_bp = bp_lib.find("sensor.camera.rgb")
        cam_bp.set_attribute("image_size_x", "1920")
        cam_bp.set_attribute("image_size_y", "1080")
        cam_bp.set_attribute("fov", "110")
        cam_t = carla.Transform(carla.Location(x=0.8, z=1.7))
        self.camera = world.spawn_actor(cam_bp, cam_t, attach_to=ego)
        self.camera.listen(self._on_image)

        # Optional rear-facing camera (PiP overlay — shows ambulance behind)
        self.rear_camera = None
        if enable_rear:
            rear_bp = bp_lib.find("sensor.camera.rgb")
            rear_bp.set_attribute("image_size_x", "480")
            rear_bp.set_attribute("image_size_y", "270")
            rear_bp.set_attribute("fov", "110")
            rear_t = carla.Transform(
                carla.Location(x=-2.5, z=1.3),
                carla.Rotation(yaw=180))
            self.rear_camera = world.spawn_actor(rear_bp, rear_t, attach_to=ego)
            self.rear_camera.listen(self._on_rear_image)

        # LiDAR
        lid_bp = bp_lib.find("sensor.lidar.ray_cast")
        lid_bp.set_attribute("channels", "64")
        lid_bp.set_attribute("range", "100")
        lid_bp.set_attribute("points_per_second", "1120000")
        lid_bp.set_attribute("rotation_frequency", "20")
        lid_t = carla.Transform(carla.Location(x=0.0, z=2.5))
        self.lidar = world.spawn_actor(lid_bp, lid_t, attach_to=ego)
        self.lidar.listen(lambda d: None)   # recorded separately if needed

    def _on_image(self, image):
        self._ctx._latest_rgb_frame = image   # Recorder reads from here

    def _on_rear_image(self, image):
        self._ctx._latest_rear_frame = image  # Recorder composites as PiP

    def destroy(self):
        if self.camera.is_alive:
            self.camera.destroy()
        if self.rear_camera and self.rear_camera.is_alive:
            self.rear_camera.destroy()
        if self.lidar.is_alive:
            self.lidar.destroy()


# ---------------------------------------------------------------------------
# Frame telemetry builder  (mirrors ScenarioBase.build_telemetry)
# ---------------------------------------------------------------------------

def _build_frame(snapshot, ego, start_ts):
    v     = ego.get_velocity()
    speed = 3.6 * math.sqrt(v.x ** 2 + v.y ** 2)   # m/s → km/h
    ctrl  = ego.get_control()
    t     = ego.get_transform()
    return {
        "timestamp":  snapshot.timestamp.elapsed_seconds,
        "elapsed_s":  snapshot.timestamp.elapsed_seconds - start_ts,
        "speed_kmh":  round(speed, 3),
        "throttle":   round(ctrl.throttle, 3),
        "brake":      round(ctrl.brake, 3),
        "steer":      round(ctrl.steer, 3),
        "x":          round(t.location.x, 3),
        "y":          round(t.location.y, 3),
        "z":          round(t.location.z, 3),
        "yaw":        round(t.rotation.yaw, 3),
    }


# ---------------------------------------------------------------------------
# ScenarioContext adapter  (used so Recorder works outside ScenarioBase)
# ---------------------------------------------------------------------------

class ScenarioContext:
    """
    Adapter giving Recorder the full ScenarioBase interface it expects:
      _latest_rgb_frame, check_trigger(), _action_events, output_dir, ego, world.
    """

    # Trigger thresholds (mirrored from scenario_base.py)
    _BRAKE_THRESH       = 0.5
    _BRAKE_SPEED_DELTA  = 5.0
    _STEER_THRESH       = 0.3
    _STEER_SUSTAIN      = 10
    _THROTTLE_THRESH    = 0.7
    _THROTTLE_DELTA     = 8.0
    _PED_BBOX_RATIO     = 0.30
    _TRIGGER_COOLDOWN   = 1.5
    _EMERGENCY_BRAKE    = 0.8   # bypass cooldown when brake >= this

    def __init__(self, scenario_id, ego, world, output_dir):
        self.scenario_id        = scenario_id
        self.ego                = ego
        self.world              = world
        self.output_dir         = Path(output_dir)
        self._action_events     = []
        self._latest_rgb_frame  = None
        self._latest_rear_frame = None   # set by SensorBundle if rear cam enabled
        self._collision_event   = None
        self._last_trigger_time = 0.0
        self._steer_sustained   = 0
        self._speed_history: list[tuple[float, float]] = []

    def check_trigger(self, frame: dict, yolo_detections=None) -> str | None:
        sim_time  = frame["timestamp"]
        # Ignore first 3s (warmup: car accelerating from standstill)
        if frame.get("elapsed_s", 999) < 3.0:
            return None
        # Emergency brakes bypass cooldown
        is_emergency = frame.get("brake", 0.0) >= self._EMERGENCY_BRAKE
        if not is_emergency and sim_time - self._last_trigger_time < self._TRIGGER_COOLDOWN:
            return None

        speed    = frame["speed_kmh"]
        brake    = frame["brake"]
        steer    = frame["steer"]
        throttle = frame["throttle"]

        # Update speed history
        self._speed_history.append((sim_time, speed))
        self._speed_history = [(t, s) for t, s in self._speed_history
                               if t >= sim_time - 3.0]

        if self._collision_event is not None:
            self._collision_event = None
            return self._fire("COLLISION_RISK", frame)

        if brake > self._BRAKE_THRESH:
            s1 = self._speed_ago(sim_time, 1.0)
            if s1 is not None and (s1 - speed) >= self._BRAKE_SPEED_DELTA:
                return self._fire("BRAKING", frame)

        if throttle > self._THROTTLE_THRESH:
            s1 = self._speed_ago(sim_time, 1.0)
            if s1 is not None and (speed - s1) >= self._THROTTLE_DELTA:
                return self._fire("ACCELERATING", frame)

        if abs(steer) > self._STEER_THRESH:
            self._steer_sustained += 1
            if self._steer_sustained >= self._STEER_SUSTAIN:
                self._steer_sustained = 0
                trigger = "TURNING" if abs(steer) > 0.5 else "LANE_CHANGE"
                return self._fire(trigger, frame)
        else:
            self._steer_sustained = 0

        if yolo_detections:
            for det in yolo_detections:
                if det.get("class_name") == "person":
                    x1, _, x2, _ = det["bbox"]
                    if (x2 - x1) / 1920.0 >= self._PED_BBOX_RATIO:
                        return self._fire("PEDESTRIAN_CLOSE", frame)

        return None

    def _fire(self, trigger_type: str, frame: dict) -> str:
        self._last_trigger_time = frame["timestamp"]
        # Deduplicate: if same trigger fired recently, update in place
        if self._action_events:
            last = self._action_events[-1]
            since_last = frame["timestamp"] - last["timestamp"]
            if last["trigger_type"] == trigger_type and since_last < 2.0:
                last["timestamp"] = frame["timestamp"]
                # Keep FIRST telemetry snapshot — best scene context
                return trigger_type
        self._action_events.append({
            "trigger_type": trigger_type,
            "timestamp":    frame["timestamp"],
            "telemetry_snapshot": frame,
        })
        return trigger_type

    def _speed_ago(self, now: float, seconds: float) -> float | None:
        target = now - seconds
        candidates = [(abs(t - target), s) for t, s in self._speed_history
                      if t <= target + 0.2]
        return min(candidates, key=lambda x: x[0])[1] if candidates else None


# ---------------------------------------------------------------------------
# Main runner class
# ---------------------------------------------------------------------------

class AdaptTrustRunner:

    HOST    = "localhost"
    PORT    = 2000
    TIMEOUT = 30.0
    FPS     = 20

    def __init__(self, scenario_id: str, run_id: int = 1,
                 output_root: str | None = None,
                 skip_map_reload: bool = False):
        if scenario_id not in SCENARIO_REGISTRY:
            raise ValueError(
                f"Unknown scenario '{scenario_id}'. "
                f"Valid ids: {sorted(SCENARIO_REGISTRY)}")

        self.scenario_id = scenario_id
        self.run_id      = run_id
        map_name, spawn_index = SCENARIO_MAP[scenario_id]
        self.map_name    = map_name
        self.spawn_index = spawn_index

        self.skip_map_reload = skip_map_reload

        root = Path(output_root) if output_root else _ROOT / "data" / "scenarios"
        self.output_dir = root / f"{scenario_id}_run{run_id}"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------

    def run(self) -> dict:
        client = carla.Client(self.HOST, self.PORT)
        client.set_timeout(self.TIMEOUT)

        # Load map if needed — skip on RTX 5060 (Blackwell) to avoid Signal 11 segfault
        world = client.get_world()
        current_map = world.get_map().name.split("/")[-1]
        if self.skip_map_reload:
            print(f"[runner] skip_map_reload=True — using current map ({current_map})")
        elif current_map != self.map_name:
            print(f"[runner] Loading {self.map_name} (current: {current_map}) ...")
            world = client.load_world(self.map_name)
            time.sleep(3.0)
        else:
            print(f"[runner] Map {self.map_name} already loaded.")

        # Synchronous mode
        settings = world.get_settings()
        settings.synchronous_mode      = True
        settings.fixed_delta_seconds   = 1.0 / self.FPS
        world.apply_settings(settings)

        # Traffic Manager sync — try 8000, fall back to a free port if already bound
        import socket as _socket
        def _tm_port_free(port):
            with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
                return s.connect_ex(("127.0.0.1", port)) != 0
        tm_port = 8000 if _tm_port_free(8000) else 8001
        try:
            tm = client.get_trafficmanager(tm_port)
        except RuntimeError:
            tm_port = 8002
            tm = client.get_trafficmanager(tm_port)
        tm.set_synchronous_mode(True)
        tm.set_global_distance_to_leading_vehicle(2.0)

        # CarlaDataProvider
        CarlaDataProvider.set_client(client)
        CarlaDataProvider.set_world(world)
        CarlaDataProvider.set_traffic_manager_port(tm_port)

        # Destroy any leftover vehicles/walkers from a previous crashed run
        for actor in world.get_actors().filter("vehicle.*"):
            actor.destroy()
        for actor in world.get_actors().filter("walker.*"):
            actor.destroy()
        world.tick()
        CarlaDataProvider.on_carla_tick()

        # Spawn ego walked back — distance is scenario-specific
        _SPAWN_BACK = {"S1_JaywalkingAdult": 50.0, "L3_NarrowStreetNav": 75.0}
        back_dist = _SPAWN_BACK.get(self.scenario_id, 0.0)
        spawn_pts = world.get_map().get_spawn_points()
        spawn_t   = spawn_pts[self.spawn_index]
        if back_dist > 0:
            wp = world.get_map().get_waypoint(spawn_t.location)
            prev_wps = wp.previous(back_dist)
            if prev_wps:
                spawn_t = prev_wps[0].transform
                spawn_t.location.z += 0.3
                print(f"[runner] Ego backed up {back_dist:.0f} m to x={spawn_t.location.x:.1f} y={spawn_t.location.y:.1f}")
            else:
                print(f"[runner] WARNING: no road behind spawn[{self.spawn_index}] — using original spawn")
        bp_lib    = world.get_blueprint_library()
        ego_bp    = bp_lib.find("vehicle.tesla.model3")
        ego       = world.spawn_actor(ego_bp, spawn_t)
        print(f"[runner] Spawned ego id={ego.id} at x={spawn_t.location.x:.1f} y={spawn_t.location.y:.1f}")

        # Register ego with CarlaDataProvider so BasicAgentBehavior can look it up
        CarlaDataProvider.register_actor(ego, spawn_t)
        CarlaDataProvider._carla_actor_pool[ego.id] = ego
        world.tick()
        CarlaDataProvider.on_carla_tick()   # populate location/velocity caches

        # Recorder context (created first so SensorBundle can push frames into it)
        ctx = ScenarioContext(
            scenario_id=self.scenario_id,
            ego=ego,
            world=world,
            output_dir=self.output_dir,
        )

        # Sensors — camera callback writes to ctx._latest_rgb_frame
        # Rear camera PiP enabled for all S4 runs (ambulance approaches from behind)
        enable_rear = self.scenario_id == "S4_EmergencyVehiclePullOver"
        sensors = SensorBundle(world, ego, ctx, self.output_dir / "raw",
                               enable_rear=enable_rear)

        rec = Recorder(ctx)

        # Build scenario
        cfg      = AdaptTrustConfig()
        ScenCls  = SCENARIO_REGISTRY[self.scenario_id]
        scenario = ScenCls([ego], cfg, world)
        tree     = scenario.scenario_tree

        duration = getattr(ScenCls, "duration", 20.0)
        print(f"[runner] Starting {self.scenario_id} (duration={duration}s)")

        result = {"scenario_id": self.scenario_id, "run_id": self.run_id}
        telemetry_frames: list[dict] = []
        npc_telemetry_frames: list[list[dict]] = []

        try:
            with rec:
                GameTime.restart()   # reset so TimeOut counts from 0
                start_ts = world.get_snapshot().timestamp.elapsed_seconds

                while True:
                    world.tick()
                    snap_ts = world.get_snapshot().timestamp
                    CarlaDataProvider.on_carla_tick()
                    GameTime.on_carla_tick(snap_ts)   # drives TimeOut atomic

                    snap   = world.get_snapshot()   # already ticked above
                    frame  = _build_frame(snap, ego, start_ts)
                    telemetry_frames.append(frame)

                    # NPC position snapshot
                    npc_frame = []
                    for idx, actor in enumerate(scenario.other_actors):
                        try:
                            if actor and actor.is_alive:
                                t = actor.get_transform()
                                v = actor.get_velocity()
                                spd = 3.6 * math.sqrt(v.x**2 + v.y**2)
                                npc_frame.append({
                                    "actor_id":   actor.id,
                                    "actor_type": actor.type_id,
                                    "index":      idx,
                                    "x":          round(t.location.x, 2),
                                    "y":          round(t.location.y, 2),
                                    "z":          round(t.location.z, 2),
                                    "yaw":        round(t.rotation.yaw, 1),
                                    "speed_kmh":  round(spd, 1),
                                    "elapsed_s":  round(frame["elapsed_s"], 3),
                                    "timestamp":  round(frame["timestamp"], 3),
                                })
                        except Exception:
                            pass
                    npc_telemetry_frames.append(npc_frame)

                    rec.record(frame)
                    tree.tick_once()

                    elapsed = frame["elapsed_s"]

                    # End condition: scenario_tree TimeOut fires (SUCCESS) after
                    # exactly self.duration seconds, or FAILURE for abnormal stop.
                    # elapsed fallback catches any edge case.
                    if (tree.status in (py_trees.common.Status.SUCCESS,
                                        py_trees.common.Status.FAILURE)
                            or elapsed >= duration + 3):
                        break

            # Write telemetry + action events (required by generator + overlay)
            telemetry_path = self.output_dir / "telemetry.json"
            telemetry_path.write_text(json.dumps(telemetry_frames, indent=2))
            print(f"[runner] telemetry.json written ({len(telemetry_frames)} frames)")

            npc_path = self.output_dir / "npc_telemetry.json"
            npc_path.write_text(json.dumps(npc_telemetry_frames, indent=2))
            actor_frames = sum(len(f) for f in npc_telemetry_frames)
            print(f"[runner] npc_telemetry.json written ({len(npc_telemetry_frames)} frames, {actor_frames} actor-frames)")

            events_path = self.output_dir / "action_events.json"
            events_path.write_text(json.dumps(ctx._action_events, indent=2))
            print(f"[runner] action_events.json written ({len(ctx._action_events)} events)")

            # ---- Scenario validator ----
            critical = getattr(ScenCls, "critical_event", None)
            if critical:
                matching = [e for e in ctx._action_events
                            if e["trigger_type"] == critical
                            and e["telemetry_snapshot"].get("brake", 0) >= 0.8]
                verdict = {
                    "scenario_id":             self.scenario_id,
                    "critical_event_required": critical,
                    "critical_event_fired":    len(matching) > 0,
                    "critical_event_count":    len(matching),
                    "PASSED":                  len(matching) > 0,
                    "note": ("Emergency brake detected" if matching
                             else "WARNING: No emergency brake >= 0.8 fired. Scenario FAILED."),
                }
            else:
                verdict = {
                    "scenario_id": self.scenario_id,
                    "PASSED": True,
                    "note": "No critical event required for this scenario.",
                }
            verdict_path = self.output_dir / "scenario_verdict.json"
            verdict_path.write_text(json.dumps(verdict, indent=2))
            print(f"\n{'PASSED' if verdict['PASSED'] else 'FAILED'}: {verdict['note']}")

            result["duration_s"]    = round(elapsed, 2)
            result["action_events"] = ctx._action_events
            result["status"]        = "ok"

            # Generate all 4 explanation conditions
            print("[runner] Generating explanations …")
            generate_all_explanations(self.output_dir)

            # Render 4 overlay videos
            print("[runner] Rendering overlay videos …")
            render_overlays(self.output_dir)

            # Add engine noise + TTS voiceover to overlay videos
            print("[runner] Adding audio to overlay videos …")
            try:
                from scripts.audio_pipeline.synthesizer import add_audio_to_videos
                add_audio_to_videos(self.output_dir)
            except Exception as _audio_exc:
                print(f"[runner] WARNING: audio pipeline failed ({_audio_exc}) — videos have no audio")

        except Exception as exc:
            result["status"] = f"error: {exc}"
            raise

        finally:
            # Restore async mode
            settings.synchronous_mode    = False
            settings.fixed_delta_seconds = None
            world.apply_settings(settings)
            tm.set_synchronous_mode(False)

            sensors.destroy()
            for actor in scenario.other_actors:
                try:
                    if actor.is_alive:
                        actor.destroy()
                except Exception:
                    pass
            try:
                ego.destroy()
            except Exception:
                pass
            CarlaDataProvider.cleanup()

        # Persist result summary
        summary_path = self.output_dir / "result.json"
        summary_path.write_text(json.dumps(result, indent=2))
        print(f"[runner] Done. Result → {summary_path}")
        return result


# ---------------------------------------------------------------------------
# Inline self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="L1_GreenLightCruise")
    parser.add_argument("--run",      type=int, default=1)
    args = parser.parse_args()

    runner = AdaptTrustRunner(scenario_id=args.scenario, run_id=args.run)
    print(json.dumps(runner.run(), indent=2))
