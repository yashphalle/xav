"""
agent_controller.py — BasicAgent wrapper for AdaptTrust scenarios.

Replaces Traffic Manager autopilot with CARLA's BasicAgent, which follows
a deterministic route defined by a destination location.  Unlike TM autopilot,
BasicAgent does not drive wherever it wants — it follows the A*-planned road
route from spawn to the destination you supply.

Usage (inside a scenario's run()):

    ap = AgentController(self.ego, self.world, target_speed_kmh=50)
    ap.set_destination(spawn_points[N].location)
    ap.enable()

    while elapsed < DURATION:
        frame = self.tick()
        ap.update(frame)   # ← runs BasicAgent.run_step() and applies control
        rec.record(frame)

    ap.disable()

Scripted override (force brake for HIGH-criticality events):

    with ap.override():
        for _ in range(30):
            self.ego.apply_control(carla.VehicleControl(brake=1.0, throttle=0.0))
            frame   = self.tick()
            ap.update(frame)   # no-op while overriding — manual control sticks
            rec.record(frame)
    # BasicAgent automatically resumes after the with-block
"""

import contextlib
import logging
import sys
from collections import deque
from pathlib import Path

import carla

# Ensure CARLA's PythonAPI agents module is importable
_CARLA_PY = "/home/meet/carla/PythonAPI/carla"
if _CARLA_PY not in sys.path:
    sys.path.insert(0, _CARLA_PY)

try:
    from agents.navigation.basic_agent import BasicAgent
    from agents.navigation.local_planner import RoadOption
    from agents.navigation.global_route_planner import GlobalRoutePlanner
    _AGENT_AVAILABLE = True
except ImportError as _e:
    _AGENT_AVAILABLE = False
    _AGENT_IMPORT_ERROR = str(_e)

logger = logging.getLogger("agent_controller")


class AgentController:
    """
    Deterministic ego-vehicle controller built on CARLA's BasicAgent.

    Key differences from AutopilotController (Traffic Manager):
    - Follows a SPECIFIC route to a destination instead of wandering.
    - Calling update(frame) every tick is what actually drives the car.
    - override() suspends BasicAgent so manual VehicleControl sticks.
    - NPCs should still use TM (configure_npc helper provided for compat).
    """

    def __init__(
        self,
        vehicle: carla.Vehicle,
        world: carla.World,
        target_speed_kmh: float = 30.0,
        ignore_traffic_lights: bool = False,
    ):
        if not _AGENT_AVAILABLE:
            raise ImportError(
                f"BasicAgent not importable from {_CARLA_PY}: {_AGENT_IMPORT_ERROR}"
            )
        self.vehicle = vehicle
        self.world = world
        self.target_speed_kmh = target_speed_kmh
        self._ignore_tl = ignore_traffic_lights

        self._destination: carla.Location | None = None
        self._agent: BasicAgent | None = None
        self._overriding = False
        self._active = False

        # Rolling speed buffer (60 frames ≈ 3 s at 20 Hz)
        self._speed_window: deque[float] = deque(maxlen=60)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_destination(self, location: carla.Location) -> None:
        """Set or change the route destination (carla.Location)."""
        self._destination = location
        if self._agent is not None:
            self._agent.set_destination(location)
            logger.info("AgentController: destination updated.")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def enable(self) -> None:
        """Create BasicAgent and begin driving the ego vehicle."""
        self._agent = BasicAgent(
            self.vehicle,
            target_speed=self.target_speed_kmh,
            opt_dict={
                "ignore_traffic_lights": self._ignore_tl,
                "ignore_vehicles": False,
            },
        )
        self._agent.ignore_traffic_lights(active=self._ignore_tl)
        self._agent.ignore_stop_signs(active=False)
        self._agent.ignore_vehicles(active=False)

        if self._destination is not None:
            self._agent.set_destination(self._destination)
        else:
            logger.warning(
                "AgentController.enable() called without a destination. "
                "Call set_destination() before update() or the car will not move."
            )

        self._overriding = False
        self._active = True
        logger.info(
            "AgentController ENABLED — target %.0f km/h, ignore_TL=%s",
            self.target_speed_kmh, self._ignore_tl,
        )

    def disable(self) -> None:
        """Stop driving — vehicle will coast."""
        self._agent = None
        self._active = False
        logger.info("AgentController DISABLED")

    # ------------------------------------------------------------------
    # Per-frame update — call once per tick
    # ------------------------------------------------------------------

    def update(self, frame: dict) -> None:
        """
        Apply BasicAgent control for this simulation step.

        Must be called every tick (after ScenarioBase.tick()) in the main loop.
        No-op when override() is active so manual VehicleControl sticks.

        Args:
            frame: Telemetry dict returned by ScenarioBase.tick().
        """
        self._speed_window.append(frame.get("speed_kmh", 0.0))

        if self._overriding or self._agent is None:
            return

        if self._agent.done():
            # Destination reached during scenario — coast, do not stop abruptly
            logger.debug("BasicAgent done (destination reached); coasting.")
            return

        control = self._agent.run_step()
        control.manual_gear_shift = False
        self.vehicle.apply_control(control)

    # ------------------------------------------------------------------
    # Scripted override context manager
    # ------------------------------------------------------------------

    @contextlib.contextmanager
    def override(self):
        """
        Temporarily suspend BasicAgent so the scenario can apply raw
        VehicleControl (e.g. emergency brake).  BasicAgent resumes
        automatically when the with-block exits.

        Example:
            with ap.override():
                for _ in range(30):
                    self.ego.apply_control(carla.VehicleControl(brake=1.0))
                    frame = self.tick()
                    ap.update(frame)   # no-op during override
        """
        self._overriding = True
        logger.debug("AgentController override START")
        try:
            yield self
        finally:
            self._overriding = False
            logger.debug("AgentController override END")

    # ------------------------------------------------------------------
    # NPC helper — kept for API compatibility with run_scenario.py
    # ------------------------------------------------------------------

    def configure_npc(
        self,
        npc: carla.Vehicle,
        traffic_manager: carla.TrafficManager,
        ignore_lights_pct: float = 0.0,
        speed_pct_diff: float = 0.0,
        distance_to_leading: float = 3.0,
    ) -> None:
        """Attach an NPC vehicle to Traffic Manager with the given settings."""
        traffic_manager.ignore_lights_percentage(npc, ignore_lights_pct)
        traffic_manager.vehicle_percentage_speed_difference(npc, speed_pct_diff)
        traffic_manager.distance_to_leading_vehicle(npc, distance_to_leading)
        npc.set_autopilot(True, traffic_manager.get_port())

    # ------------------------------------------------------------------
    # Speed queries
    # ------------------------------------------------------------------

    @property
    def current_speed_kmh(self) -> float:
        return self._speed_window[-1] if self._speed_window else 0.0

    @property
    def average_speed_kmh(self) -> float:
        if not self._speed_window:
            return 0.0
        return sum(self._speed_window) / len(self._speed_window)

    def is_stopped(self, threshold_kmh: float = 1.0) -> bool:
        return self.current_speed_kmh < threshold_kmh

    def __repr__(self) -> str:
        state = "OVERRIDE" if self._overriding else ("ON" if self._active else "OFF")
        return (
            f"AgentController(vehicle={self.vehicle.id}, "
            f"state={state}, speed={self.current_speed_kmh:.1f} km/h)"
        )
