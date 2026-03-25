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

# ---- project paths --------------------------------------------------------
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, "/home/meet/scenario_runner")
sys.path.insert(0, "/home/meet/carla/PythonAPI/carla")
sys.path.insert(0, "/home/meet/carla/PythonAPI/carla/agents")

import carla
from srunner.scenariomanager.carla_data_provider import CarlaDataProvider
from scripts.scenarios.adaptrust_scenarios import (
    SCENARIO_REGISTRY, SCENARIO_MAP, AdaptTrustConfig,
)
from scripts.data_collection.recorder import Recorder


# ---------------------------------------------------------------------------
# Sensor helpers
# ---------------------------------------------------------------------------

class SensorBundle:
    """Attaches RGB camera and LiDAR to ego; exposes latest frames."""

    def __init__(self, world, ego, output_dir: Path):
        self.output_dir = output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        bp_lib = world.get_blueprint_library()

        # RGB camera
        cam_bp = bp_lib.find("sensor.camera.rgb")
        cam_bp.set_attribute("image_size_x", "1280")
        cam_bp.set_attribute("image_size_y", "720")
        cam_bp.set_attribute("fov", "90")
        cam_t = carla.Transform(carla.Location(x=2.0, z=1.4))
        self.camera = world.spawn_actor(cam_bp, cam_t, attach_to=ego)
        self.camera.listen(self._on_image)
        self._latest_image = None

        # LiDAR
        lid_bp = bp_lib.find("sensor.lidar.ray_cast")
        lid_bp.set_attribute("channels", "64")
        lid_bp.set_attribute("range", "100")
        lid_bp.set_attribute("points_per_second", "1120000")
        lid_bp.set_attribute("rotation_frequency", "20")
        lid_t = carla.Transform(carla.Location(x=0.0, z=2.5))
        self.lidar = world.spawn_actor(lid_bp, lid_t, attach_to=ego)
        self.lidar.listen(self._on_lidar)
        self._latest_lidar = None

    def _on_image(self, image):
        self._latest_image = image

    def _on_lidar(self, data):
        self._latest_lidar = data

    def destroy(self):
        if self.camera.is_alive:
            self.camera.destroy()
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
    Thin adapter that gives Recorder the interface it expects from ScenarioBase.
    Recorder needs: scenario_id, ego, world, output_dir, _action_events.
    """

    def __init__(self, scenario_id, ego, world, output_dir):
        self.scenario_id   = scenario_id
        self.ego           = ego
        self.world         = world
        self.output_dir    = Path(output_dir)
        self._action_events = []


# ---------------------------------------------------------------------------
# Main runner class
# ---------------------------------------------------------------------------

class AdaptTrustRunner:

    HOST    = "localhost"
    PORT    = 2000
    TIMEOUT = 30.0
    FPS     = 20

    def __init__(self, scenario_id: str, run_id: int = 1,
                 output_root: str | None = None):
        if scenario_id not in SCENARIO_REGISTRY:
            raise ValueError(
                f"Unknown scenario '{scenario_id}'. "
                f"Valid ids: {sorted(SCENARIO_REGISTRY)}")

        self.scenario_id = scenario_id
        self.run_id      = run_id
        map_name, spawn_index = SCENARIO_MAP[scenario_id]
        self.map_name    = map_name
        self.spawn_index = spawn_index

        root = Path(output_root) if output_root else _ROOT / "data" / "scenarios"
        self.output_dir = root / f"{scenario_id}_run{run_id}"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------

    def run(self) -> dict:
        client = carla.Client(self.HOST, self.PORT)
        client.set_timeout(self.TIMEOUT)

        # Load map if needed
        world = client.get_world()
        if world.get_map().name.split("/")[-1] != self.map_name:
            print(f"[runner] Loading {self.map_name} ...")
            world = client.load_world(self.map_name)
            time.sleep(3.0)

        # Synchronous mode
        settings = world.get_settings()
        settings.synchronous_mode      = True
        settings.fixed_delta_seconds   = 1.0 / self.FPS
        world.apply_settings(settings)

        # Traffic Manager sync
        tm = client.get_trafficmanager(8000)
        tm.set_synchronous_mode(True)
        tm.set_global_distance_to_leading_vehicle(2.0)

        # CarlaDataProvider
        CarlaDataProvider.set_client(client)
        CarlaDataProvider.set_world(world)
        CarlaDataProvider.set_traffic_manager_port(8000)

        # Tick once so CDP caches are warm
        world.tick()
        CarlaDataProvider.on_carla_tick()

        # Spawn ego at spawn_index
        spawn_pts = world.get_map().get_spawn_points()
        spawn_t   = spawn_pts[self.spawn_index]
        bp_lib    = world.get_blueprint_library()
        ego_bp    = bp_lib.find("vehicle.tesla.model3")
        ego       = world.spawn_actor(ego_bp, spawn_t)
        print(f"[runner] Spawned ego id={ego.id} at spawn[{self.spawn_index}]")

        # Sensors
        sensors = SensorBundle(world, ego, self.output_dir / "raw")

        # Recorder context
        ctx = ScenarioContext(
            scenario_id=self.scenario_id,
            ego=ego,
            world=world,
            output_dir=self.output_dir,
        )
        rec = Recorder(ctx)

        # Build scenario
        cfg      = AdaptTrustConfig()
        ScenCls  = SCENARIO_REGISTRY[self.scenario_id]
        scenario = ScenCls([ego], cfg, world)
        tree     = scenario.scenario_tree

        duration = getattr(ScenCls, "duration", 20.0)
        print(f"[runner] Starting {self.scenario_id} (duration={duration}s)")

        result = {"scenario_id": self.scenario_id, "run_id": self.run_id}

        try:
            with rec:
                start_ts = world.get_snapshot().timestamp.elapsed_seconds

                while True:
                    world.tick()
                    CarlaDataProvider.on_carla_tick()

                    snap   = world.get_snapshot()
                    frame  = _build_frame(snap, ego, start_ts)
                    rec.record(frame)
                    tree.tick_once()

                    elapsed = frame["elapsed_s"]

                    # End condition: behavior tree completed OR duration elapsed
                    if (tree.status == py_trees.common.Status.SUCCESS
                            or tree.status == py_trees.common.Status.FAILURE
                            or elapsed >= duration + 2):
                        break

            result["duration_s"]    = round(elapsed, 2)
            result["action_events"] = ctx._action_events
            result["status"]        = "ok"

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
