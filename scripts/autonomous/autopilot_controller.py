"""
autopilot_controller.py — Traffic Manager autopilot wrapper for AdaptTrust.

Wraps CARLA's built-in Traffic Manager so all 20 scenarios get consistent
autopilot behaviour without re-implementing motion planning.

Usage:
    from scripts.autonomous.autopilot_controller import AutopilotController

    # Inside a ScenarioBase.run():
    ap = AutopilotController(ego, traffic_manager)
    ap.enable()

    for _ in range(steps):
        frame = self.tick()
        ap.update(frame)        # updates internal speed history

    ap.disable()

Temporary manual override (e.g. force a hard brake for a scenario):
    with ap.override():
        self.ego.apply_control(carla.VehicleControl(brake=1.0))
        for _ in range(10):
            self.tick()
    # autopilot resumes automatically after the with-block
"""

import contextlib
import logging
import math
import time
from collections import deque

import carla

logger = logging.getLogger("autopilot_controller")


class AutopilotController:
    """
    Thin wrapper around CARLA Traffic Manager autopilot.

    Responsibilities:
    - Enable / disable autopilot on the ego vehicle.
    - Apply consistent Traffic Manager settings for the experiment
      (obey traffic lights, run at map speed limit).
    - Provide a context-manager override for scripted interventions.
    - Track a rolling speed window so scenarios can query current speed
      without re-reading vehicle state.
    """

    def __init__(
        self,
        ego: carla.Vehicle,
        traffic_manager: carla.TrafficManager,
        target_speed_kmh: float | None = None,
        tm_port: int = 8000,
    ):
        """
        Args:
            ego:               The hero vehicle actor.
            traffic_manager:   TrafficManager instance from the CARLA client.
            target_speed_kmh:  If set, clamps ego to this speed via TM's
                               percentage_speed_difference.  None = map speed limit.
            tm_port:           Traffic Manager port (default 8000).
        """
        self.ego = ego
        self.tm = traffic_manager
        self.tm_port = tm_port
        self.target_speed_kmh = target_speed_kmh

        self._autopilot_active = False
        self._override_active = False

        # Rolling speed buffer — last 60 frames (~3 s at 20 Hz)
        self._speed_window: deque[float] = deque(maxlen=60)

    # ------------------------------------------------------------------
    # Enable / disable
    # ------------------------------------------------------------------

    def enable(self) -> None:
        """
        Activate Traffic Manager autopilot with experiment-standard settings.

        Settings applied:
          - ignore_lights_percentage = 0   → always obey traffic lights
          - ignore_signs_percentage  = 0   → always obey stop/yield signs
          - ignore_walkers_percentage = 0  → always yield to pedestrians
          - vehicle_percentage_speed_difference = 0  → run at map speed limit
            (or adjusted if target_speed_kmh is set)
          - auto_lane_change = True        → TM handles lane changes
          - distance_to_leading_vehicle = 3.0 m  → safe following distance
        """
        self._configure_tm()
        self.ego.set_autopilot(True, self.tm_port)
        self._autopilot_active = True
        logger.info(
            "Autopilot ENABLED on vehicle %s (TM port %d, target=%.0f km/h)",
            self.ego.id,
            self.tm_port,
            self.target_speed_kmh if self.target_speed_kmh is not None else -1,
        )

    def disable(self) -> None:
        """Disable autopilot, leaving the vehicle in neutral/coast."""
        self.ego.set_autopilot(False, self.tm_port)
        self._autopilot_active = False
        logger.info("Autopilot DISABLED on vehicle %s", self.ego.id)

    def _configure_tm(self) -> None:
        """Apply consistent TM settings to the ego vehicle."""
        tm = self.tm

        # Safety behaviour — never skip lights/signs/pedestrians
        tm.ignore_lights_percentage(self.ego, 0.0)
        tm.ignore_signs_percentage(self.ego, 0.0)
        tm.ignore_walkers_percentage(self.ego, 0.0)

        # Speed: 0 % difference = drive at map speed limit
        # Positive % = slower; negative % = faster (capped by TM internally)
        if self.target_speed_kmh is not None:
            # Derive the map speed limit to compute a % offset
            speed_limit = self.ego.get_speed_limit()  # km/h
            if speed_limit and speed_limit > 0:
                pct_diff = ((speed_limit - self.target_speed_kmh) / speed_limit) * 100.0
            else:
                pct_diff = 0.0
            tm.vehicle_percentage_speed_difference(self.ego, pct_diff)
            logger.debug(
                "TM speed set: limit=%.0f km/h → pct_diff=%.1f%%",
                speed_limit, pct_diff,
            )
        else:
            tm.vehicle_percentage_speed_difference(self.ego, 0.0)

        # Lane change and following distance
        tm.auto_lane_change(self.ego, True)
        tm.distance_to_leading_vehicle(self.ego, 3.0)

    # ------------------------------------------------------------------
    # Per-frame update
    # ------------------------------------------------------------------

    def update(self, frame: dict) -> None:
        """
        Call once per tick (after ScenarioBase.tick()) to maintain internal state.

        Args:
            frame: Telemetry dict returned by ScenarioBase.tick().
        """
        self._speed_window.append(frame["speed_kmh"])

    # ------------------------------------------------------------------
    # Speed queries
    # ------------------------------------------------------------------

    @property
    def current_speed_kmh(self) -> float:
        """Most recent speed reading, or 0 if no data yet."""
        return self._speed_window[-1] if self._speed_window else 0.0

    @property
    def average_speed_kmh(self) -> float:
        """Rolling average over the speed window (~3 s)."""
        if not self._speed_window:
            return 0.0
        return sum(self._speed_window) / len(self._speed_window)

    def is_stopped(self, threshold_kmh: float = 1.0) -> bool:
        """True if the vehicle has been essentially stationary recently."""
        return self.current_speed_kmh < threshold_kmh

    # ------------------------------------------------------------------
    # Temporary manual override
    # ------------------------------------------------------------------

    @contextlib.contextmanager
    def override(self):
        """
        Context manager for scripted interventions that temporarily disable
        autopilot and let the caller apply raw VehicleControl.

        Example:
            with ap.override():
                ego.apply_control(carla.VehicleControl(brake=1.0, hand_brake=True))
                for _ in range(20):
                    scenario.tick()
            # autopilot automatically re-enabled here
        """
        was_active = self._autopilot_active
        if was_active:
            self.ego.set_autopilot(False, self.tm_port)
            self._override_active = True
            logger.debug("Override START — autopilot suspended on vehicle %s", self.ego.id)
        try:
            yield self
        finally:
            if was_active:
                self._configure_tm()
                self.ego.set_autopilot(True, self.tm_port)
                self._override_active = False
                logger.debug("Override END — autopilot resumed on vehicle %s", self.ego.id)

    # ------------------------------------------------------------------
    # NPC helpers (used by scenario scripts to populate traffic)
    # ------------------------------------------------------------------

    def configure_npc(
        self,
        npc: carla.Vehicle,
        ignore_lights_pct: float = 0.0,
        speed_pct_diff: float = 0.0,
        distance_to_leading: float = 3.0,
    ) -> None:
        """
        Apply TM settings to an NPC vehicle spawned by a scenario.

        Args:
            npc:                 NPC vehicle actor.
            ignore_lights_pct:   0–100; non-zero makes the NPC run red lights
                                 (useful for high-criticality scenarios).
            speed_pct_diff:      TM speed adjustment (0 = speed limit).
            distance_to_leading: Following distance in metres.
        """
        self.tm.ignore_lights_percentage(npc, ignore_lights_pct)
        self.tm.vehicle_percentage_speed_difference(npc, speed_pct_diff)
        self.tm.distance_to_leading_vehicle(npc, distance_to_leading)
        npc.set_autopilot(True, self.tm_port)

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        state = "OVERRIDE" if self._override_active else ("ON" if self._autopilot_active else "OFF")
        return (
            f"AutopilotController(vehicle={self.ego.id}, "
            f"state={state}, speed={self.current_speed_kmh:.1f} km/h)"
        )
