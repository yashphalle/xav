"""
scenario_base.py — Abstract base class for all AdaptTrust CARLA scenarios.

All 20 scenario scripts inherit from ScenarioBase and implement run().

Usage (standalone smoke test):
    python scripts/scenarios/scenario_base.py
"""

import abc
import json
import logging
import math
import time
from pathlib import Path

import carla

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("scenario_base")


class ScenarioFailed(RuntimeError):
    """Raised by verify() when a scenario did not produce its required events."""

# ---------------------------------------------------------------------------
# Action trigger thresholds (from project brief)
# ---------------------------------------------------------------------------
TRIGGER_BRAKE_THRESHOLD = 0.5          # brake pedal value
TRIGGER_BRAKE_SPEED_DELTA = 5.0        # km/h drop in 1 s
TRIGGER_STEER_THRESHOLD = 0.3          # steer value
TRIGGER_STEER_SUSTAIN_FRAMES = 10      # ~0.5 s at 20 Hz tick
TRIGGER_THROTTLE_THRESHOLD = 0.7
TRIGGER_THROTTLE_SPEED_DELTA = 8.0     # km/h gain in 1 s
TRIGGER_PEDESTRIAN_BBOX_RATIO = 0.30   # fraction of frame width
TRIGGER_SPEED_CHANGE_DELTA = 15.0      # km/h in 2 s
TRIGGER_COOLDOWN_SECONDS = 3.0         # min gap between events


class ScenarioBase(abc.ABC):
    """
    Reusable base for every AdaptTrust scenario.

    Subclass contract:
        - Override run() to implement scenario-specific logic.
        - Call self.tick() each simulation step (returns current telemetry dict).
        - Optionally call self.check_trigger() to detect action events.

    Context manager:
        with ScenarioBase(...) as scenario:
            scenario.run()
    """

    # Sensor blueprint IDs
    _RGB_BP       = "sensor.camera.rgb"
    _SEG_BP       = "sensor.camera.semantic_segmentation"
    _IMU_BP       = "sensor.other.imu"
    _GNSS_BP      = "sensor.other.gnss"
    _COLLISION_BP = "sensor.other.collision"
    _EGO_BP       = "vehicle.tesla.model3"

    def __init__(
        self,
        map_name: str,
        spawn_index: int = 0,
        host: str = "localhost",
        port: int = 2000,
        timeout: float = 10.0,
        fixed_delta_seconds: float = 0.05,
        data_root: str | None = None,
        scenario_id: str | None = None,
        skip_map_reload: bool = False,
    ):
        """
        Args:
            map_name:             CARLA map to load, e.g. 'Town01'.
            spawn_index:          Index into world.get_map().get_spawn_points().
            host/port/timeout:    CARLA server connection parameters.
            fixed_delta_seconds:  Simulation tick length (0.05 = 20 Hz).
            data_root:            Base path for output data.  Defaults to
                                  <repo_root>/data/scenarios/.
            scenario_id:          Folder name for this run, e.g. 'L1_highway_cruise_run1'.
            skip_map_reload:      If True, never call client.load_world() — use whatever
                                  map CARLA already has loaded.  Pass when CARLA is already
                                  on the correct map to avoid the Signal 11 segfault that
                                  occurs on some GPUs (e.g. RTX 5060) during map switches.
        """
        self.map_name = map_name
        self.spawn_index = spawn_index
        self.host = host
        self.port = port
        self.timeout = timeout
        self.fixed_delta_seconds = fixed_delta_seconds
        self.skip_map_reload = skip_map_reload

        repo_root = Path(__file__).resolve().parents[2]
        self.data_root = Path(data_root) if data_root else repo_root / "data" / "scenarios"
        self.scenario_id = scenario_id or self.__class__.__name__
        self.output_dir = self.data_root / self.scenario_id
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # CARLA handles — populated in _connect()
        self.client: carla.Client | None = None
        self.world: carla.World | None = None
        self.traffic_manager: carla.TrafficManager | None = None
        self.ego: carla.Vehicle | None = None

        # Sensor data queues (populated by callbacks)
        self._latest_rgb_frame: carla.Image | None = None
        self._latest_seg_frame: carla.Image | None = None
        self._latest_imu: carla.IMUMeasurement | None = None
        self._latest_gnss: carla.GnssMeasurement | None = None
        self._collision_event: carla.CollisionEvent | None = None

        # Actors to destroy on cleanup
        self._actors: list[carla.Actor] = []

        # Telemetry
        self._telemetry: list[dict] = []
        self._action_events: list[dict] = []

        # Trigger state
        self._last_trigger_time: float = 0.0
        self._steer_sustained_frames: int = 0
        self._speed_history: list[tuple[float, float]] = []  # (sim_time, speed_kmh)

    # ------------------------------------------------------------------
    # Connection & setup
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        logger.info("Connecting to CARLA at %s:%d …", self.host, self.port)
        self.client = carla.Client(self.host, self.port)
        self.client.set_timeout(self.timeout)

        server_version = self.client.get_server_version()
        logger.info("Connected — CARLA server version %s", server_version)

        current_map = self.client.get_world().get_map().name
        if self.skip_map_reload:
            logger.info(
                "Map reload skipped (skip_map_reload=True) — using current world (%s).",
                current_map,
            )
            self.world = self.client.get_world()
        elif not current_map.endswith(self.map_name):
            logger.info("Loading map %s (current: %s) …", self.map_name, current_map)
            self.world = self.client.load_world(self.map_name)
            # Give UE4 time to finish loading
            time.sleep(2.0)
        else:
            logger.info("Map %s already loaded.", self.map_name)
            self.world = self.client.get_world()

        # Synchronous mode
        settings = self.world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = self.fixed_delta_seconds
        self.world.apply_settings(settings)
        logger.info(
            "Synchronous mode ON — tick %.3f s (%.0f Hz)",
            self.fixed_delta_seconds,
            1.0 / self.fixed_delta_seconds,
        )

        self.traffic_manager = self.client.get_trafficmanager()
        self.traffic_manager.set_synchronous_mode(True)

    def _spawn_ego(self) -> None:
        bp_lib = self.world.get_blueprint_library()
        ego_bp = bp_lib.find(self._EGO_BP)
        ego_bp.set_attribute("role_name", "hero")

        spawn_points = self.world.get_map().get_spawn_points()
        if self.spawn_index >= len(spawn_points):
            raise ValueError(
                f"spawn_index {self.spawn_index} out of range "
                f"(map has {len(spawn_points)} spawn points)"
            )
        transform = spawn_points[self.spawn_index]

        self.ego = self.world.try_spawn_actor(ego_bp, transform)
        if self.ego is None:
            raise RuntimeError(
                f"Failed to spawn ego vehicle at spawn point {self.spawn_index}. "
                "Point may be occupied — try a different spawn_index."
            )
        self._actors.append(self.ego)
        logger.info("Ego spawned: %s at spawn point %d", self.ego.id, self.spawn_index)

    def _attach_sensors(self) -> None:
        bp_lib = self.world.get_blueprint_library()

        # Shared camera transform (front-center, roof height)
        cam_transform = carla.Transform(
            carla.Location(x=0.8, z=1.7),
            carla.Rotation(pitch=0.0),
        )

        # --- RGB camera ---
        rgb_bp = bp_lib.find(self._RGB_BP)
        rgb_bp.set_attribute("image_size_x", "1920")
        rgb_bp.set_attribute("image_size_y", "1080")
        rgb_bp.set_attribute("fov", "110")
        rgb_cam = self.world.spawn_actor(rgb_bp, cam_transform, attach_to=self.ego)
        rgb_cam.listen(lambda img: setattr(self, "_latest_rgb_frame", img))
        self._actors.append(rgb_cam)

        # --- Semantic segmentation camera ---
        seg_bp = bp_lib.find(self._SEG_BP)
        seg_bp.set_attribute("image_size_x", "1920")
        seg_bp.set_attribute("image_size_y", "1080")
        seg_bp.set_attribute("fov", "110")
        seg_cam = self.world.spawn_actor(seg_bp, cam_transform, attach_to=self.ego)
        seg_cam.listen(lambda img: setattr(self, "_latest_seg_frame", img))
        self._actors.append(seg_cam)

        # --- IMU ---
        imu_bp = bp_lib.find(self._IMU_BP)
        imu = self.world.spawn_actor(
            imu_bp,
            carla.Transform(),
            attach_to=self.ego,
        )
        imu.listen(lambda m: setattr(self, "_latest_imu", m))
        self._actors.append(imu)

        # --- GNSS ---
        gnss_bp = bp_lib.find(self._GNSS_BP)
        gnss = self.world.spawn_actor(
            gnss_bp,
            carla.Transform(),
            attach_to=self.ego,
        )
        gnss.listen(lambda m: setattr(self, "_latest_gnss", m))
        self._actors.append(gnss)

        # --- Collision detector ---
        col_bp = bp_lib.find(self._COLLISION_BP)
        col = self.world.spawn_actor(
            col_bp,
            carla.Transform(),
            attach_to=self.ego,
        )
        col.listen(lambda e: setattr(self, "_collision_event", e))
        self._actors.append(col)

        logger.info("Attached %d sensors to ego vehicle.", 5)

    # ------------------------------------------------------------------
    # Per-frame helpers
    # ------------------------------------------------------------------

    def tick(self) -> dict:
        """
        Advance simulation by one step and return the current telemetry frame.
        Always call this instead of world.tick() directly.
        """
        self.world.tick()

        v = self.ego.get_velocity()
        speed_ms = math.sqrt(v.x**2 + v.y**2 + v.z**2)
        speed_kmh = speed_ms * 3.6

        ctrl = self.ego.get_control()
        accel = self.ego.get_acceleration()

        sim_time = self.world.get_snapshot().timestamp.elapsed_seconds

        frame: dict = {
            "timestamp": sim_time,
            "speed_kmh": round(speed_kmh, 3),
            "throttle": round(ctrl.throttle, 4),
            "brake": round(ctrl.brake, 4),
            "steer": round(ctrl.steer, 4),
            "gear": ctrl.gear,
            "accel_x": round(accel.x, 4),
            "accel_y": round(accel.y, 4),
            "accel_z": round(accel.z, 4),
        }

        if self._latest_imu:
            frame["imu_accel_x"] = round(self._latest_imu.accelerometer.x, 4)
            frame["imu_accel_y"] = round(self._latest_imu.accelerometer.y, 4)
            frame["imu_accel_z"] = round(self._latest_imu.accelerometer.z, 4)
            frame["imu_gyro_x"]  = round(self._latest_imu.gyroscope.x, 4)
            frame["imu_gyro_y"]  = round(self._latest_imu.gyroscope.y, 4)
            frame["imu_gyro_z"]  = round(self._latest_imu.gyroscope.z, 4)

        if self._latest_gnss:
            frame["latitude"]  = round(self._latest_gnss.latitude, 6)
            frame["longitude"] = round(self._latest_gnss.longitude, 6)

        # Traffic light state — "red" | "yellow" | "green" | "off" | "none"
        # "none" means the ego is not currently governed by a traffic light.
        try:
            if self.ego.is_at_traffic_light():
                tl_state = str(self.ego.get_traffic_light().get_state())
                frame["traffic_light_state"] = tl_state.split(".")[-1].lower()
            else:
                frame["traffic_light_state"] = "none"
        except Exception:
            frame["traffic_light_state"] = "none"

        self._telemetry.append(frame)

        # Keep a short speed history for delta-speed triggers
        self._speed_history.append((sim_time, speed_kmh))
        # Trim to last 3 seconds
        cutoff = sim_time - 3.0
        self._speed_history = [e for e in self._speed_history if e[0] >= cutoff]

        return frame

    def check_trigger(self, frame: dict, yolo_detections: list | None = None) -> str | None:
        """
        Evaluate action trigger thresholds against the current telemetry frame.

        Args:
            frame:            Dict returned by tick().
            yolo_detections:  Optional list of YOLO detection dicts from the current frame.
                              Each dict should have keys: class_name, bbox (x1,y1,x2,y2),
                              confidence.

        Returns:
            Trigger type string (e.g. 'BRAKING') or None if no trigger fires.
        """
        sim_time = frame["timestamp"]

        # Cooldown guard
        if sim_time - self._last_trigger_time < TRIGGER_COOLDOWN_SECONDS:
            return None

        speed_now = frame["speed_kmh"]
        brake     = frame["brake"]
        steer     = frame["steer"]
        throttle  = frame["throttle"]

        # -- COLLISION_RISK (highest priority) --
        if self._collision_event is not None:
            self._collision_event = None  # consume
            return self._fire_trigger("COLLISION_RISK", frame)

        # -- BRAKING: brake pedal > 0.5 AND speed dropped > 5 km/h in last 1 s --
        if brake > TRIGGER_BRAKE_THRESHOLD:
            speed_1s_ago = self._speed_1s_ago(sim_time)
            if speed_1s_ago is not None and (speed_1s_ago - speed_now) >= TRIGGER_BRAKE_SPEED_DELTA:
                return self._fire_trigger("BRAKING", frame)

        # -- ACCELERATING: throttle > 0.7 AND speed gained > 8 km/h in last 1 s --
        if throttle > TRIGGER_THROTTLE_THRESHOLD:
            speed_1s_ago = self._speed_1s_ago(sim_time)
            if speed_1s_ago is not None and (speed_now - speed_1s_ago) >= TRIGGER_THROTTLE_SPEED_DELTA:
                return self._fire_trigger("ACCELERATING", frame)

        # -- LANE_CHANGE / TURNING: steer > 0.3 sustained for ~0.5 s --
        if abs(steer) > TRIGGER_STEER_THRESHOLD:
            self._steer_sustained_frames += 1
            if self._steer_sustained_frames >= TRIGGER_STEER_SUSTAIN_FRAMES:
                self._steer_sustained_frames = 0
                trigger = "TURNING" if abs(steer) > 0.5 else "LANE_CHANGE"
                return self._fire_trigger(trigger, frame)
        else:
            self._steer_sustained_frames = 0

        # -- SPEED_CHANGE: speed delta > 15 km/h over 2 s --
        speed_2s_ago = self._speed_ago(sim_time, 2.0)
        if speed_2s_ago is not None and abs(speed_now - speed_2s_ago) >= TRIGGER_SPEED_CHANGE_DELTA:
            return self._fire_trigger("SPEED_CHANGE", frame)

        # -- PEDESTRIAN_CLOSE: YOLO pedestrian bbox > 30% of frame width --
        if yolo_detections:
            for det in yolo_detections:
                if det.get("class_name") == "person":
                    x1, _, x2, _ = det["bbox"]
                    bbox_width_ratio = (x2 - x1) / 1920.0
                    if bbox_width_ratio >= TRIGGER_PEDESTRIAN_BBOX_RATIO:
                        return self._fire_trigger("PEDESTRIAN_CLOSE", frame)

        return None

    def _fire_trigger(self, trigger_type: str, frame: dict) -> str:
        sim_time = frame["timestamp"]
        self._last_trigger_time = sim_time
        event = {
            "trigger_type": trigger_type,
            "timestamp": sim_time,
            "telemetry_snapshot": frame,
        }
        self._action_events.append(event)
        logger.info("ACTION TRIGGER: %s at t=%.2f s", trigger_type, sim_time)
        return trigger_type

    def _speed_1s_ago(self, now: float) -> float | None:
        return self._speed_ago(now, 1.0)

    def _speed_ago(self, now: float, seconds: float) -> float | None:
        """Return speed recorded ~`seconds` ago, or None if not enough history."""
        target = now - seconds
        candidates = [(abs(t - target), s) for t, s in self._speed_history if t <= now - seconds + 0.2]
        if not candidates:
            return None
        return min(candidates, key=lambda x: x[0])[1]

    # ------------------------------------------------------------------
    # Save outputs
    # ------------------------------------------------------------------

    def save_telemetry(self) -> None:
        path = self.output_dir / "telemetry.json"
        with open(path, "w") as f:
            json.dump(self._telemetry, f, indent=2)
        logger.info("Telemetry saved → %s (%d frames)", path, len(self._telemetry))

    def save_action_events(self) -> None:
        path = self.output_dir / "action_events.json"
        with open(path, "w") as f:
            json.dump(self._action_events, f, indent=2)
        logger.info("Action events saved → %s (%d events)", path, len(self._action_events))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def setup(self) -> None:
        """Connect, load map, spawn ego, attach sensors."""
        self._connect()
        self._spawn_ego()
        self._attach_sensors()
        # Warm-up ticks so sensors produce data before run() starts
        for _ in range(10):
            self.world.tick()
        logger.info("Setup complete — scenario '%s' ready.", self.scenario_id)

    def clean_up(self) -> None:
        """Destroy all spawned actors and restore async mode."""
        logger.info("Cleaning up %d actors …", len(self._actors))
        # Destroy in reverse order (sensors before vehicle)
        for actor in reversed(self._actors):
            if actor.is_alive:
                actor.destroy()
        self._actors.clear()

        if self.world is not None:
            settings = self.world.get_settings()
            settings.synchronous_mode = False
            settings.fixed_delta_seconds = None
            self.world.apply_settings(settings)
            logger.info("Synchronous mode OFF.")

    @abc.abstractmethod
    def run(self, ap=None, rec=None) -> dict:
        """
        Implement scenario logic here.

        When called by run_scenario.py, `ap` and `rec` are already constructed
        and started.  Scenarios only need to:
          - Set weather / NPCs
          - Drive the tick loop:  frame = self.tick(); rec.record(frame)
          - Return metadata

        When called standalone (e.g. in tests), ap and rec may be None and
        the scenario is responsible for constructing them if needed.

        Returns:
            Metadata dict, e.g.:
            {
                "scenario_id": "L1_highway_cruise",
                "map": "Town04",
                "duration_s": 30.0,
                "npc_count": 5,
            }
        """

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self):
        self.setup()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.save_telemetry()
        self.save_action_events()
        self.clean_up()
        # Propagate exceptions
        return False


# ---------------------------------------------------------------------------
# Smoke test — run directly to verify CARLA connectivity & base class works
# ---------------------------------------------------------------------------

class _SmokeTestScenario(ScenarioBase):
    """Minimal scenario: spawn ego, run 5 s, clean up."""

    def run(self, ap=None, rec=None) -> dict:
        logger.info("Smoke test: running for 5 simulated seconds …")
        start = self.world.get_snapshot().timestamp.elapsed_seconds
        frames = 0
        triggers_seen = []

        while True:
            frame = self.tick()
            trigger = self.check_trigger(frame)
            if trigger:
                triggers_seen.append(trigger)

            elapsed = frame["timestamp"] - start
            if frames % 20 == 0:
                logger.info(
                    "  t=%.1f s | speed=%.1f km/h | brake=%.2f | throttle=%.2f",
                    elapsed, frame["speed_kmh"], frame["brake"], frame["throttle"],
                )

            frames += 1
            if elapsed >= 5.0:
                break

        logger.info(
            "Smoke test complete: %d frames, %d trigger(s): %s",
            frames, len(triggers_seen), triggers_seen,
        )
        return {
            "scenario_id": "smoke_test",
            "map": self.map_name,
            "frames": frames,
            "triggers": triggers_seen,
        }


if __name__ == "__main__":
    import sys

    scenario = _SmokeTestScenario(
        map_name="Town01",
        spawn_index=0,
        scenario_id="smoke_test_run1",
    )

    try:
        with scenario as s:
            result = s.run()
        print("\nResult:", json.dumps(result, indent=2))
        print("\nSMOKE TEST PASSED")
        sys.exit(0)
    except Exception as e:
        logger.error("SMOKE TEST FAILED: %s", e, exc_info=True)
        sys.exit(1)
