"""
adaptrust_scenarios.py
All 9 AdaptTrust scenario classes using py_trees behavior trees.

Scenarios:
  LOW criticality  : L1_GreenLightCruise, L2_SlowLeadOvertake, L3_NarrowStreetNav
  MEDIUM criticality: M1_YellowLightStop, M2_CrosswalkYield, M3_HighwayMergeYield
  HIGH criticality : H1_PedestrianDart, H2_HighwayCutIn, H3_RedLightRunner

Usage (from adaptrust_runner.py):
    from srunner.scenarios.adaptrust_scenarios import SCENARIO_REGISTRY, AdaptTrustConfig
    cfg = AdaptTrustConfig()
    ScenarioCls = SCENARIO_REGISTRY["H1_PedestrianDart"]
    scenario = ScenarioCls([ego], cfg, world)
    # each tick:
    world.tick()
    CarlaDataProvider.on_carla_tick()
    scenario.scenario_tree.tick_once()

sys.path must include ~/carla/PythonAPI/carla before importing this module.
"""

import sys
import math
from pathlib import Path
_HOME = Path.home()
sys.path.insert(0, str(_HOME / "scenario_runner"))
sys.path.insert(0, str(_HOME / "carla/PythonAPI/carla"))
sys.path.insert(0, str(_HOME / "carla/PythonAPI/carla/agents"))

import carla
import py_trees

from srunner.scenarios.basic_scenario import BasicScenario
from srunner.scenariomanager.carla_data_provider import CarlaDataProvider
from srunner.scenariomanager.scenarioatomics.atomic_behaviors import (
    AtomicBehavior,
    BasicAgentBehavior,
    WaitForever,
    AccelerateToCatchUp,
    LaneChange,
    WaypointFollower,
    ConstantVelocityAgentBehavior,
    ActorTransformSetter,
)
from srunner.scenariomanager.scenarioatomics.atomic_trigger_conditions import (
    DriveDistance,
    InTriggerDistanceToVehicle,
    InTriggerDistanceToLocation,
)


# ---------------------------------------------------------------------------
# Minimal config — bypasses ScenarioConfigurationParser / XML entirely
# ---------------------------------------------------------------------------

class AdaptTrustConfig:
    """Drop-in replacement for ScenarioConfiguration."""
    route           = None        # disables route_mode in BasicScenario
    weather         = carla.WeatherParameters.WetCloudyNoon
    friction        = None
    other_actors    = []
    trigger_points  = []          # disables automatic trigger in behavior_tree
    route_var_name  = None


# ---------------------------------------------------------------------------
# Custom atomics
# ---------------------------------------------------------------------------

class EgoBasicAgentBehavior(BasicAgentBehavior):
    """BasicAgentBehavior with ignore_traffic_lights and ignore_vehicles options."""

    def __init__(self, actor, target_location, target_speed, ignore_tl=True,
                 ignore_vehicles=False, name="EgoBasicAgent"):
        super().__init__(actor, target_location=target_location,
                         target_speed=target_speed, name=name)
        self._ignore_tl       = ignore_tl
        self._ignore_vehicles = ignore_vehicles

    def initialise(self):
        super().initialise()
        self._agent.ignore_traffic_lights(active=self._ignore_tl)
        self._agent.ignore_vehicles(active=self._ignore_vehicles)


class HoldThrottle(AtomicBehavior):
    """Apply constant throttle to ego (no steering override) until terminated."""

    def __init__(self, actor, throttle=0.75, name="HoldThrottle"):
        super().__init__(name, actor)
        self._throttle = throttle

    def update(self):
        self._actor.apply_control(carla.VehicleControl(throttle=self._throttle))
        return py_trees.common.Status.RUNNING


class ForceEgoBrake(AtomicBehavior):
    """Apply hard braking to ego for a fixed number of ticks, then SUCCESS."""

    def __init__(self, actor, ticks=40, brake=1.0, name="ForceEgoBrake"):
        super().__init__(name, actor)
        self._ticks = ticks
        self._brake = brake
        self._count = 0

    def initialise(self):
        self._count = 0

    def update(self):
        ctrl = carla.VehicleControl(brake=self._brake, throttle=0.0)
        self._actor.apply_control(ctrl)
        self._count += 1
        if self._count >= self._ticks:
            return py_trees.common.Status.SUCCESS
        return py_trees.common.Status.RUNNING


class WaitUntilEgoClose(AtomicBehavior):
    """SUCCESS when ego is within `distance` metres of a target location."""

    def __init__(self, ego, target_location, distance=30.0, name="WaitUntilEgoClose"):
        super().__init__(name, ego)
        self._target = target_location
        self._dist   = distance

    def update(self):
        loc = self._actor.get_location()
        d   = loc.distance(self._target)
        if d <= self._dist:
            return py_trees.common.Status.SUCCESS
        return py_trees.common.Status.RUNNING


class KeepWalkerMoving(AtomicBehavior):
    """Apply WalkerControl every tick for a fixed number of ticks, then SUCCESS."""

    def __init__(self, walker, direction, speed=4.0, ticks=40,
                 name="KeepWalkerMoving"):
        super().__init__(name, walker)
        self._dir   = direction
        self._speed = speed
        self._ticks = ticks
        self._count = 0

    def initialise(self):
        self._count = 0

    def update(self):
        if self._actor and self._actor.is_alive:
            self._actor.apply_control(
                carla.WalkerControl(direction=self._dir,
                                    speed=self._speed,
                                    jump=False))
        self._count += 1
        if self._count >= self._ticks:
            return py_trees.common.Status.SUCCESS
        return py_trees.common.Status.RUNNING


class KeepWalkerMovingForever(AtomicBehavior):
    """Apply WalkerControl every tick indefinitely (RUNNING until terminated)."""

    def __init__(self, walker, direction, speed=3.5, name="KeepWalkerMovingForever"):
        super().__init__(name, walker)
        self._dir   = direction
        self._speed = speed

    def update(self):
        if self._actor and self._actor.is_alive:
            self._actor.apply_control(
                carla.WalkerControl(direction=self._dir,
                                    speed=self._speed,
                                    jump=False))
        return py_trees.common.Status.RUNNING


class SetActorThrottle(AtomicBehavior):
    """Apply constant throttle to a vehicle NPC indefinitely (for crossing NPCs)."""

    def __init__(self, actor, throttle=0.5, name="SetActorThrottle"):
        super().__init__(name, actor)
        self._throttle = throttle

    def update(self):
        if self._actor and self._actor.is_alive:
            self._actor.apply_control(
                carla.VehicleControl(throttle=self._throttle, steer=0.0, brake=0.0))
        return py_trees.common.Status.RUNNING


class SetTLToState(AtomicBehavior):
    """One-shot: find nearest TL to ego and set it to the given state (frozen)."""

    def __init__(self, ego, state, name="SetTLToState"):
        super().__init__(name, ego)
        self._state = state

    def update(self):
        world = CarlaDataProvider.get_world()
        tl_actors = list(world.get_actors().filter("traffic.traffic_light"))
        ego_loc = self._actor.get_location()
        try:
            if self._actor.is_at_traffic_light():
                tl = self._actor.get_traffic_light()
            else:
                tl = min(tl_actors,
                         key=lambda t: t.get_location().distance(ego_loc))
            tl.set_state(self._state)
            tl.freeze(True)
        except Exception:
            pass
        return py_trees.common.Status.SUCCESS


class SetAllTLsToState(AtomicBehavior):
    """One-shot: set ALL traffic lights in the map to the given state (frozen)."""

    def __init__(self, state, name="SetAllTLsToState"):
        super().__init__(name)
        self._state = state

    def update(self):
        world = CarlaDataProvider.get_world()
        for tl in world.get_actors().filter("traffic.traffic_light"):
            tl.set_state(self._state)
            tl.freeze(True)
        return py_trees.common.Status.SUCCESS


class DirectLaneChange(AtomicBehavior):
    """
    Steer NPC into an adjacent lane using raw VehicleControl — no Blackboard
    / ActorsWithController dependency.

    Phase 1 (ticks_steer ticks): apply lateral steer + throttle to drift across.
    Phase 2 (ticks_straight ticks): neutralise steer so the NPC tracks straight
    in the new lane before returning SUCCESS.
    """

    def __init__(self, actor, direction='right', speed_mps=22.0,
                 steer=0.10, ticks_steer=40, ticks_straight=20,
                 name="DirectLaneChange"):
        super().__init__(name, actor)
        # CARLA convention: positive steer = LEFT, negative steer = RIGHT
        self._steer_val = -steer if direction == 'right' else steer
        self._speed_mps = speed_mps
        self._ticks_steer = ticks_steer
        self._ticks_straight = ticks_straight
        self._count = 0

    def initialise(self):
        self._count = 0

    def update(self):
        if not (self._actor and self._actor.is_alive):
            return py_trees.common.Status.SUCCESS

        v = self._actor.get_velocity()
        cur_spd = math.sqrt(v.x**2 + v.y**2 + v.z**2)

        if self._count < self._ticks_steer:
            if cur_spd > self._speed_mps * 1.05:
                # Brake to target speed before/during lane change
                ctrl = carla.VehicleControl(throttle=0.0, steer=self._steer_val,
                                            brake=0.5)
            else:
                throttle = 0.4 if cur_spd < self._speed_mps else 0.0
                ctrl = carla.VehicleControl(throttle=throttle,
                                            steer=self._steer_val, brake=0.0)
        else:
            # Straighten out — hold speed
            throttle = 0.4 if cur_spd < self._speed_mps else 0.0
            ctrl = carla.VehicleControl(throttle=throttle, steer=0.0, brake=0.0)

        self._actor.apply_control(ctrl)
        self._count += 1

        total = self._ticks_steer + self._ticks_straight
        return (py_trees.common.Status.SUCCESS
                if self._count >= total
                else py_trees.common.Status.RUNNING)


class ForceLaneChange(AtomicBehavior):
    """One-shot: instruct TM to force NPC into the right lane (toward ego lane)."""

    def __init__(self, npc, tm, name="ForceLaneChange"):
        super().__init__(name, npc)
        self._tm = tm

    def update(self):
        if self._actor and self._actor.is_alive:
            self._tm.force_lane_change(self._actor, False)   # False = change RIGHT
        return py_trees.common.Status.SUCCESS


class PrintSpeedCheckpoint(AtomicBehavior):
    """
    Prints ego speed + position on the first tick, then returns SUCCESS
    so a Sequence can advance immediately to the next step.
    """

    def __init__(self, ego, label, name="PrintCheckpoint"):
        super().__init__(name, ego)
        self._label = label
        self._done  = False

    def update(self):
        if not self._done:
            v   = self._actor.get_velocity()
            spd = math.sqrt(v.x**2 + v.y**2 + v.z**2) * 3.6
            loc = self._actor.get_location()
            print(f"[L3 CHECKPOINT] {self._label}: "
                  f"speed={spd:.1f} km/h  x={loc.x:.1f} y={loc.y:.1f}")
            self._done = True
        return py_trees.common.Status.SUCCESS


class NarrowStreetDriver(AtomicBehavior):
    """
    L3 ego driver combining three behaviours in one atomic:

    1. ROUTING  — BasicAgent plans the route and handles steering for road curves.
    2. SPEED    — drops to slow_speed within slow_dist of any parked NPC, then
                  recovers to normal_speed once clear.
    3. WEAVE    — adds a lateral steer correction that pushes the ego away from
                  whichever side each NPC is on, creating a visible slalom effect.

    NPC layout (±2.5 m offset): cars sit at the road shoulder.  The weave is
    cosmetic — ego safely passes without correction — but adds visible lateral
    deviation that justifies the spatial-reasoning explanation condition.

    Steer correction: negate copysign so the correction opposes the NPC's side.
    NPC to the right (lat_comp > 0)  →  −correction (steer left / away)
    NPC to the left  (lat_comp < 0)  →  +correction (steer right / away)
    """

    def __init__(self, ego, dest, normal_speed, slow_speed, npcs,
                 slow_dist=14.0, avoid_dist=18.0, steer_gain=0.12,
                 plan=None, name="NarrowStreetDriver"):
        super().__init__(name, ego)
        self._dest         = dest
        self._plan         = plan
        self._normal_speed = normal_speed
        self._slow_speed   = slow_speed
        self._npcs         = [(i, n) for i, n in enumerate(npcs) if n is not None]
        self._slow_dist    = slow_dist
        self._avoid_dist   = avoid_dist
        self._steer_gain   = steer_gain
        self._logged       = set()
        self._agent        = None

    def initialise(self):
        from agents.navigation.basic_agent import BasicAgent
        self._agent = BasicAgent(self._actor, target_speed=self._normal_speed)
        self._agent.ignore_traffic_lights(active=True)
        self._agent.ignore_vehicles(active=True)
        if self._plan is not None:
            try:
                self._agent.set_global_plan(self._plan, stop_waypoint_creation=True, clean_queue=True)
            except TypeError:
                # Older CARLA versions have different signature
                self._agent.set_global_plan(self._plan)
        else:
            self._agent.set_destination(self._dest)
        self._logged.clear()

    def update(self):
        if not (self._actor and self._actor.is_alive):
            return py_trees.common.Status.SUCCESS

        ego_t   = self._actor.get_transform()
        ego_loc = ego_t.location
        fwd     = ego_t.get_forward_vector()
        right   = ego_t.get_right_vector()

        min_dist         = float('inf')
        steer_correction = 0.0

        for i, npc in self._npcs:
            if not npc.is_alive:
                continue
            npc_loc = npc.get_location()
            d = ego_loc.distance(npc_loc)

            # Only update min_dist for NPCs ahead of ego — prevents slowing for passed cars
            dx = npc_loc.x - ego_loc.x
            dy = npc_loc.y - ego_loc.y
            if dx * fwd.x + dy * fwd.y > 0 and d < min_dist:
                min_dist = d

            # One-shot checkpoint log when entering slow zone
            if d <= self._slow_dist and i not in self._logged:
                v   = self._actor.get_velocity()
                spd = math.sqrt(v.x**2 + v.y**2 + v.z**2) * 3.6
                # Determine actual side from geometry (works for any layout)
                dx = npc_loc.x - ego_loc.x
                dy = npc_loc.y - ego_loc.y
                lat = dx * right.x + dy * right.y
                side = 'right' if lat > 0 else 'left'
                print(f"[L3 CHECKPOINT] NPC{i+1} ({side}): "
                      f"speed={spd:.1f} km/h  "
                      f"x={ego_loc.x:.1f} y={ego_loc.y:.1f}")
                self._logged.add(i)

            # Lateral correction only for NPCs within avoid_dist and ahead of ego
            if d > self._avoid_dist:
                continue
            dx = npc_loc.x - ego_loc.x
            dy = npc_loc.y - ego_loc.y
            if dx * fwd.x + dy * fwd.y < -4.0:   # NPC is behind — skip
                continue

            # Which side is the NPC?  positive lat_comp = NPC is to the RIGHT
            lat_comp = dx * right.x + dy * right.y
            strength = (self._avoid_dist - d) / self._avoid_dist   # 1→0 as d→avoid_dist

            # Steer away from the NPC (negate: CARLA positive steer = RIGHT)
            steer_correction += -math.copysign(1.0, lat_comp) * strength * self._steer_gain

        # Speed
        target_spd = (self._slow_speed if min_dist < self._slow_dist
                      else self._normal_speed)
        self._agent.set_target_speed(target_spd)

        # Apply base control + lateral correction
        ctrl = self._agent.run_step()
        ctrl.steer = max(-1.0, min(1.0, ctrl.steer + steer_correction))
        self._actor.apply_control(ctrl)
        return py_trees.common.Status.RUNNING


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _far_waypoint(world, actor, dist_m=3000.0):
    """Return a location dist_m ahead along the road from actor's current position."""
    wp  = world.get_map().get_waypoint(actor.get_location())
    wps = wp.next(dist_m)
    if wps:
        return wps[0].transform.location
    return world.get_map().get_spawn_points()[-1].location


def _straight_waypoint(world, actor, dist_m=200.0):
    """Walk dist_m ahead always choosing the waypoint most aligned with current
    forward direction — avoids turns at junctions."""
    wp  = world.get_map().get_waypoint(actor.get_location())
    fwd = actor.get_transform().get_forward_vector()
    traveled = 0.0
    step = 2.0
    while traveled < dist_m:
        nexts = wp.next(step)
        if not nexts:
            break
        wp = max(nexts, key=lambda w: (
            w.transform.get_forward_vector().x * fwd.x +
            w.transform.get_forward_vector().y * fwd.y
        ))
        traveled += step
    return wp.transform.location


def _straight_plan(world, actor, dist_m=200.0, step=2.0):
    """Return a list of (waypoint, RoadOption.STRAIGHT) tuples walking straight
    ahead — for use with BasicAgent.set_global_plan() to bypass route planner."""
    from agents.navigation.local_planner import RoadOption
    wp  = world.get_map().get_waypoint(actor.get_location())
    fwd = actor.get_transform().get_forward_vector()
    plan = []
    traveled = 0.0
    while traveled < dist_m:
        nexts = wp.next(step)
        if not nexts:
            break
        wp = max(nexts, key=lambda w: (
            w.transform.get_forward_vector().x * fwd.x +
            w.transform.get_forward_vector().y * fwd.y
        ))
        plan.append((wp, RoadOption.STRAIGHT))
        traveled += step
    return plan


def _freeze_tls_green(world):
    """Freeze all traffic lights to GREEN."""
    for tl in world.get_actors().filter("traffic.traffic_light"):
        tl.set_state(carla.TrafficLightState.Green)
        tl.freeze(True)


# ---------------------------------------------------------------------------
# Base class with shared overrides
# ---------------------------------------------------------------------------

class AdaptTrustScenario(BasicScenario):
    """
    Shared base for all 9 AdaptTrust scenarios.

    Subclasses MUST define:
      - map_name, spawn_index, duration, target_speed
      - _do_initialize_actors(world)  — spawn NPCs, store refs in self.other_actors
      - _do_create_behavior()         — return a py_trees node
      - freeze_tls (bool, default True) — whether to freeze all TLs green at start
    """

    freeze_tls     = True
    target_speed   = 50.0    # km/h
    duration       = 20.0    # seconds
    critical_event = None    # override in HIGH criticality subclasses

    def __init__(self, ego_vehicles, config, world,
                 debug_mode=False, terminate_on_failure=False):
        self.timeout = self.duration   # scenario_tree TimeOut ends after exactly duration s
        super().__init__(
            name=self.__class__.__name__,
            ego_vehicles=ego_vehicles,
            config=config,
            world=world,
            debug_mode=debug_mode,
            terminate_on_failure=terminate_on_failure,
            criteria_enable=False,
        )

    def _initialize_environment(self, world):
        world.set_weather(carla.WeatherParameters.WetCloudyNoon)
        if self.freeze_tls:
            _freeze_tls_green(world)

    def _initialize_actors(self, config):
        self._do_initialize_actors(self.world)

    def _do_initialize_actors(self, world):
        pass   # override in subclass if NPCs needed

    def _create_behavior(self):
        inner = self._do_create_behavior()
        # Wrap in SUCCESS_ON_ALL + WaitForever so the behavior_tree Sequence
        # never completes early. Only TimeOut(self.duration) in scenario_tree
        # can end the scenario. Inner behavior still runs and applies controls.
        wrapper = py_trees.composites.Parallel(
            self.__class__.__name__ + "_DurationGuard",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ALL)
        wrapper.add_child(inner)
        wrapper.add_child(WaitForever())
        return wrapper

    def _do_create_behavior(self):
        raise NotImplementedError

    def _create_test_criteria(self):
        return []

    # Convenience: destination far ahead from current ego position
    def _dest(self, dist_m=2000.0):
        return _far_waypoint(self.world, self.ego_vehicles[0], dist_m)

    def _ego(self):
        return self.ego_vehicles[0]


# ===========================================================================
# LOW criticality scenarios
# ===========================================================================

class L1_GreenLightCruise(AdaptTrustScenario):
    """Town03 — drive at 50 km/h through all-green lights for 20 s."""

    duration     = 20.0
    target_speed = 50.0

    def _do_create_behavior(self):
        return EgoBasicAgentBehavior(
            self._ego(), self._dest(), self.target_speed, ignore_tl=True,
            name="L1_Drive")


class L2_SlowLeadOvertake(AdaptTrustScenario):
    """
    Town04 — slow NPC (~20 km/h) is 70 m ahead; ego cruises at 60 km/h,
    catches up, changes lane to overtake, drives past, then merges back.
    """

    duration     = 30.0
    target_speed = 60.0

    def _do_initialize_actors(self, world):
        bp_lib  = world.get_blueprint_library()
        car_bps = [b for b in bp_lib.filter("vehicle.*")
                   if b.get_attribute("number_of_wheels").as_int() == 4]
        bp = car_bps[0] if car_bps else bp_lib.filter("vehicle.*")[0]

        ego_wp    = world.get_map().get_waypoint(self._ego().get_location())
        ahead_wps = ego_wp.next(70.0)   # far enough for ego to cruise before closing
        if not ahead_wps:
            self._lead_npc = None
            print("[L2] WARNING: no waypoint 70 m ahead — no NPC spawned")
            return

        t = carla.Transform(
            ahead_wps[0].transform.location + carla.Location(z=0.5),
            ahead_wps[0].transform.rotation)
        npc = world.try_spawn_actor(bp, t)
        if not npc:
            self._lead_npc = None
            print("[L2] WARNING: NPC spawn failed")
            return

        self._lead_npc = npc
        self.other_actors.append(npc)
        CarlaDataProvider.register_actor(npc, t)
        CarlaDataProvider._carla_actor_pool[npc.id] = npc
        world.tick()
        CarlaDataProvider.on_carla_tick()
        # Town04 speed limit ≈ 90 km/h → 78 % below ≈ 20 km/h
        tm = CarlaDataProvider.get_client().get_trafficmanager(
            CarlaDataProvider.get_traffic_manager_port())
        npc.set_autopilot(True, tm.get_port())
        tm.vehicle_percentage_speed_difference(npc, 78)
        tm.ignore_lights_percentage(npc, 100)
        tm.auto_lane_change(npc, False)
        print(f"[L2] Lead NPC id={npc.id} spawned 70 m ahead at ~20 km/h")

    def _do_create_behavior(self):
        from srunner.scenariomanager.timer import TimeOut as TOut

        ego  = self._ego()
        npc  = getattr(self, "_lead_npc", None)
        dest = self._dest(2000.0)
        spd  = self.target_speed / 3.6   # m/s

        seq = py_trees.composites.Sequence("L2_SlowLeadOvertake")

        # Phase 1 — cruise at 60 km/h until within 15 m of the slow NPC
        phase1 = py_trees.composites.Parallel(
            "L2_Phase1_Approach",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        phase1.add_child(EgoBasicAgentBehavior(ego, dest, self.target_speed,
                                               ignore_tl=True, name="L2_Cruise"))
        if npc:
            phase1.add_child(InTriggerDistanceToVehicle(
                ego, npc, 15.0, name="L2_CloseEnough"))
        phase1.add_child(TOut(12.0, name="L2_Phase1Timeout"))
        seq.add_child(phase1)

        # Phase 2 — brake to 20 km/h then change to left lane
        # Low speed keeps yaw change small so BasicAgent can recover cleanly
        seq.add_child(DirectLaneChange(ego, direction='right',
                                       speed_mps=20.0 / 3.6,
                                       steer=0.05, ticks_steer=35, ticks_straight=30,
                                       name="L2_OvertakeLaneChange"))

        # Phase 3 — drive past NPC in left lane (ignore vehicles so no slowdown)
        phase3 = py_trees.composites.Parallel(
            "L2_Phase3_Pass",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        phase3.add_child(EgoBasicAgentBehavior(ego, dest, self.target_speed,
                                               ignore_tl=True, ignore_vehicles=True,
                                               name="L2_OvertakeDrive"))
        phase3.add_child(DriveDistance(ego, 60.0, name="L2_PassDist"))
        phase3.add_child(TOut(6.0, name="L2_Phase3Timeout"))
        seq.add_child(phase3)

        # Phase 4 — brake to 20 km/h then merge back into right lane
        seq.add_child(DirectLaneChange(ego, direction='left',
                                       speed_mps=20.0 / 3.6,
                                       steer=0.05, ticks_steer=35, ticks_straight=30,
                                       name="L2_MergeBack"))

        # Phase 5 — resume normal cruise
        seq.add_child(EgoBasicAgentBehavior(ego, dest, self.target_speed,
                                            ignore_tl=True, name="L2_Resume"))
        return seq


class L3_NarrowStreetNav(AdaptTrustScenario):
    """
    Town02 — ego drives at 15 km/h through a narrow street with 4 parked cars.
    Cars alternate right/left, each shifted 0.8 m into the lane from its side,
    forcing the ego to slow and squeeze past each one.

    Telemetry: prints [L3 CHECKPOINT] NPC1-4 with dist and speed each time
    the ego gets within 10 m of a parked car.

    Ideal behaviour:
      t≈ 5 s — approaches NPC1 (right), brakes to ~6-10 km/h, CHECKPOINT fires
      t≈ 9 s — clears NPC1, returns to ~13-15 km/h
      t≈12 s — NPC2 (left), slows again
      t≈17 s — NPC3 (right), t≈22 s — NPC4 (left)
      t=30 s — scenario ends
    """

    duration     = 30.0
    target_speed = 60.0   # km/h cruise speed

    # Preferred blueprints — variety of makes/sizes so parked cars look different.
    # Falls back gracefully if a blueprint isn't available in this CARLA build.
    _PARKED_BLUEPRINTS = [
        "vehicle.tesla.model3",
        "vehicle.audi.tt",
        "vehicle.chevrolet.impala",
        "vehicle.lincoln.mkz_2017",
        "vehicle.bmw.grandtourer",
        "vehicle.toyota.prius",
        "vehicle.ford.mustang",
        "vehicle.seat.leon",
    ]

    def _do_initialize_actors(self, world):
        bp_lib  = world.get_blueprint_library()
        car_bps = [b for b in bp_lib.filter("vehicle.*")
                   if b.get_attribute("number_of_wheels").as_int() == 4]

        # Build a pool of distinct blueprints, cycling through preferred list
        bp_pool = []
        for name in self._PARKED_BLUEPRINTS:
            match = bp_lib.find(name) if bp_lib.find(name) else None
            if match:
                bp_pool.append(match)
        if not bp_pool:
            bp_pool = car_bps   # fallback: use whatever is available
        # Deduplicate by id, preserve order
        seen = set()
        bp_pool = [b for b in bp_pool if not (b.id in seen or seen.add(b.id))]

        # Use the original map spawn point as fixed reference so parked cars
        # stay at their correct world positions even when ego spawns further back.
        spawn_pts = world.get_map().get_spawn_points()
        ego_wp = world.get_map().get_waypoint(spawn_pts[0].location)

        # Layout: (distance_m, side_sign)
        #   side_sign = -1 → LEFT side, +1 → RIGHT side
        # Only 3 cars on the straight section — road turns right at ~35m
        # so all post-turn cars are removed to keep scenario on straight road.
        layout = [
            (10.0, -1),   # NPC1  — left
            (20.0, -1),   # NPC2  — left
            (30.0, -1),   # NPC3  — left
        ]

        self._parked_npcs = []
        for i, (dist, sign) in enumerate(layout):
            ahead_wps = ego_wp.next(dist)
            if not ahead_wps:
                self._parked_npcs.append(None)
                print(f"[L3] WARNING: no waypoint at dist={dist:.0f}m — NPC{i+1} skipped")
                continue

            wp    = ahead_wps[0]
            right = wp.transform.get_right_vector()
            # 2.5 m offset clears ego collision mesh (ego half ~1.0m + NPC half ~0.9m
            # = 1.9m minimum; 2.5m gives 0.6m air gap at lane centre).
            side = sign * 2.5
            loc  = carla.Location(
                x=wp.transform.location.x + side * right.x,
                y=wp.transform.location.y + side * right.y,
                z=wp.transform.location.z + 0.3,
            )
            t      = carla.Transform(loc, wp.transform.rotation)
            bp     = bp_pool[i % len(bp_pool)]   # rotate through blueprints
            npc    = world.try_spawn_actor(bp, t)
            if npc:
                npc.set_simulate_physics(False)
                npc.set_autopilot(False)
                self.other_actors.append(npc)
                CarlaDataProvider.register_actor(npc, t)
                CarlaDataProvider._carla_actor_pool[npc.id] = npc
                self._parked_npcs.append(npc)
                label = 'left' if sign < 0 else 'right'
                print(f"[L3] NPC{i+1} ({bp.id}) spawned at dist={dist:.0f}m {label}  "
                      f"x={loc.x:.1f} y={loc.y:.1f}")
            else:
                self._parked_npcs.append(None)
                print(f"[L3] WARNING: NPC{i+1} spawn FAILED at dist={dist:.0f}m "
                      f"x={loc.x:.1f} y={loc.y:.1f} — skipped")

        world.tick()
        CarlaDataProvider.on_carla_tick()

    def _do_create_behavior(self):
        ego  = self._ego()
        plan = _straight_plan(self.world, ego, dist_m=200.0)
        return NarrowStreetDriver(
            ego=ego,
            dest=_straight_waypoint(self.world, ego, dist_m=200.0),
            plan=plan,
            normal_speed=self.target_speed,   # 50 km/h cruise
            slow_speed=10.0,                   # 10 km/h past each car
            npcs=getattr(self, "_parked_npcs", []),
            slow_dist=25.0,    # start braking 25 m before each NPC
            avoid_dist=30.0,   # start weave correction at 30 m
            steer_gain=0.22,   # lateral steer bias (~0.55 m lateral shift at peak)
            name="L3_Drive")


# ===========================================================================
# MEDIUM criticality scenarios
# ===========================================================================

class M1_YellowLightStop(AdaptTrustScenario):
    """Town03 — TL turns Yellow at t=8 s; BasicAgent sees it and brakes gently."""

    duration     = 20.0
    target_speed = 50.0
    freeze_tls   = True   # start GREEN, flip one to YELLOW at t=8s via behavior

    def _do_create_behavior(self):
        ego = self._ego()
        dest = self._dest()
        seq = py_trees.composites.Sequence("M1_YellowLight")

        # Phase 1: drive for 8 s then set nearest TL to Yellow
        phase1 = py_trees.composites.Parallel(
            "M1_Phase1_Approach",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        # Use ignore_tl=False so BasicAgent respects TL changes after Phase1
        phase1.add_child(EgoBasicAgentBehavior(ego, dest, self.target_speed,
                                               ignore_tl=True, name="M1_Drive1"))
        from srunner.scenariomanager.timer import TimeOut as TOut
        phase1.add_child(TOut(8.0, name="M1_WarmupTimer"))
        seq.add_child(phase1)

        # One-shot: flip ALL TLs to Yellow so ego sees it regardless of position
        seq.add_child(SetAllTLsToState(carla.TrafficLightState.Yellow,
                                       name="M1_SetAllYellow"))

        # Phase 2: continue driving — agent will see Yellow and slow
        # ignore_tl=False so it reacts to the Yellow TL we just set
        seq.add_child(EgoBasicAgentBehavior(ego, dest, self.target_speed,
                                            ignore_tl=False, name="M1_Drive2"))
        return seq


class M2_CrosswalkYield(AdaptTrustScenario):
    """Town02 — pedestrian crosses at crosswalk ~20 m ahead; ego yields (soft brake)."""

    duration     = 20.0
    target_speed = 25.0

    def _do_initialize_actors(self, world):
        bp_lib    = world.get_blueprint_library()
        walkers   = list(bp_lib.filter("walker.pedestrian.*"))
        walker_bp = walkers[0] if walkers else None
        if walker_bp is None:
            self._walker = None
            return

        ego_t = self._ego().get_transform()
        fwd   = ego_t.get_forward_vector()
        right = ego_t.get_right_vector()

        walker_loc = carla.Location(
            x=ego_t.location.x + 20.0 * fwd.x - 3.0 * right.x,
            y=ego_t.location.y + 20.0 * fwd.y - 3.0 * right.y,
            z=ego_t.location.z + 0.5,
        )
        self._walk_dir = carla.Vector3D(x=-right.x, y=-right.y, z=0.0)
        walker = world.try_spawn_actor(
            walker_bp,
            carla.Transform(walker_loc,
                            carla.Rotation(yaw=ego_t.rotation.yaw + 90)))
        self._walker = walker
        if walker:
            self.other_actors.append(walker)
            world.tick()

    def _do_create_behavior(self):
        ego  = self._ego()
        dest = self._dest()
        seq  = py_trees.composites.Sequence("M2_CrosswalkYield")

        # Phase 1: approach for 6 s
        phase1 = py_trees.composites.Parallel(
            "M2_Phase1_Approach",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        phase1.add_child(EgoBasicAgentBehavior(ego, dest, self.target_speed,
                                               ignore_tl=True, name="M2_Drive1"))
        from srunner.scenariomanager.timer import TimeOut as TOut
        phase1.add_child(TOut(6.0, name="M2_WarmupTimer"))
        seq.add_child(phase1)

        # Phase 2: walker crosses + soft ego brake simultaneously (30 ticks = 1.5 s)
        if getattr(self, "_walker", None) and self._walker.is_alive:
            phase2 = py_trees.composites.Parallel(
                "M2_Phase2_Yield",
                policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ALL)
            phase2.add_child(KeepWalkerMoving(self._walker, self._walk_dir,
                                              speed=3.5, ticks=30,
                                              name="M2_Walker"))
            phase2.add_child(ForceEgoBrake(ego, ticks=30, brake=0.6,
                                           name="M2_SoftBrake"))
            seq.add_child(phase2)

        # Phase 3: resume
        seq.add_child(EgoBasicAgentBehavior(ego, dest, self.target_speed,
                                            ignore_tl=True, name="M2_Drive2"))
        return seq


class M3_HighwayMergeYield(AdaptTrustScenario):
    """Town04 — NPC merges from left lane into ego lane ahead; ego yields (soft brake)."""

    duration     = 25.0
    target_speed = 70.0

    def _do_initialize_actors(self, world):
        bp_lib  = world.get_blueprint_library()
        car_bps = [b for b in bp_lib.filter("vehicle.*")
                   if b.get_attribute("number_of_wheels").as_int() == 4]
        bp = car_bps[0] if car_bps else bp_lib.filter("vehicle.*")[0]

        ego_wp    = world.get_map().get_waypoint(self._ego().get_location())
        ahead_wps = ego_wp.next(20.0)
        npc = None
        if ahead_wps:
            left_wp = ahead_wps[0].get_left_lane()
            if left_wp is None or left_wp.lane_type != carla.LaneType.Driving:
                left_wp = ahead_wps[0].get_right_lane()
            if left_wp is None or left_wp.lane_type != carla.LaneType.Driving:
                self._merge_npc = None
                return
            t = carla.Transform(
                left_wp.transform.location + carla.Location(z=0.5),
                left_wp.transform.rotation)
            npc = world.try_spawn_actor(bp, t)

        self._merge_npc = npc
        if npc:
            self.other_actors.append(npc)
            tm = CarlaDataProvider.get_client().get_trafficmanager(CarlaDataProvider.get_traffic_manager_port())
            npc.set_autopilot(True, tm.get_port())
            tm.ignore_lights_percentage(npc, 100)
            tm.vehicle_percentage_speed_difference(npc, -5)   # slightly faster
            tm.auto_lane_change(npc, False)

    def _do_create_behavior(self):
        ego  = self._ego()
        dest = self._dest()
        seq  = py_trees.composites.Sequence("M3_MergeYield")

        # Phase 1: approach for 8 s
        phase1 = py_trees.composites.Parallel(
            "M3_Phase1_Approach",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        phase1.add_child(EgoBasicAgentBehavior(ego, dest, self.target_speed,
                                               ignore_tl=True, name="M3_Drive1"))
        from srunner.scenariomanager.timer import TimeOut as TOut
        phase1.add_child(TOut(8.0, name="M3_WarmupTimer"))
        seq.add_child(phase1)

        # Force merge + soft brake
        npc = getattr(self, "_merge_npc", None)
        tm  = CarlaDataProvider.get_client().get_trafficmanager(CarlaDataProvider.get_traffic_manager_port())
        phase2 = py_trees.composites.Parallel(
            "M3_Phase2_Merge",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        if npc and npc.is_alive:
            phase2.add_child(ForceLaneChange(npc, tm, name="M3_ForceMerge"))
        phase2.add_child(ForceEgoBrake(ego, ticks=25, brake=0.5,
                                       name="M3_SoftBrake"))
        seq.add_child(phase2)

        # Phase 3: resume
        seq.add_child(EgoBasicAgentBehavior(ego, dest, self.target_speed,
                                            ignore_tl=True, name="M3_Drive2"))
        return seq


# ===========================================================================
# HIGH criticality scenarios
# ===========================================================================

class H1_PedestrianDart(AdaptTrustScenario):
    """Town02 — pedestrian darts from right into road; ego emergency-brakes 2 s."""

    duration        = 20.0
    target_speed    = 30.0
    critical_event  = "BRAKING"

    def _do_initialize_actors(self, world):
        bp_lib    = world.get_blueprint_library()
        # Prefer child-height blueprints
        _CHILD_IDS = ("walker.pedestrian.0008", "walker.pedestrian.0012",
                      "walker.pedestrian.0014", "walker.pedestrian.0016")
        child_bps  = [b for b in bp_lib.filter("walker.pedestrian.*")
                      if b.id in _CHILD_IDS]
        walker_bp  = child_bps[0] if child_bps else \
                     (list(bp_lib.filter("walker.pedestrian.*")) or [None])[0]
        if walker_bp is None:
            self._walker = None
            return

        ego_t = self._ego().get_transform()
        fwd   = ego_t.get_forward_vector()
        right = ego_t.get_right_vector()

        walker_loc = carla.Location(
            x=ego_t.location.x + 40.0 * fwd.x + 4.0 * right.x,
            y=ego_t.location.y + 40.0 * fwd.y + 4.0 * right.y,
            z=ego_t.location.z + 0.5,
        )
        self._walk_dir = carla.Vector3D(x=-right.x, y=-right.y, z=0.0)

        walker = world.try_spawn_actor(
            walker_bp,
            carla.Transform(walker_loc,
                            carla.Rotation(yaw=ego_t.rotation.yaw + 90)))
        self._walker = walker
        if walker:
            self.other_actors.append(walker)
            world.tick()

    def _do_create_behavior(self):
        ego  = self._ego()
        dest = self._dest()
        seq  = py_trees.composites.Sequence("H1_PedestrianDart")

        # Phase 1: drive until ego has moved 20 m
        phase1 = py_trees.composites.Parallel(
            "H1_Phase1_Approach",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        phase1.add_child(EgoBasicAgentBehavior(ego, dest, self.target_speed,
                                               ignore_tl=True, name="H1_Drive1"))
        phase1.add_child(DriveDistance(ego, 20.0, name="H1_DistanceTrigger"))
        seq.add_child(phase1)

        # Phase 2: walker darts + ego emergency-brakes (40 ticks ≈ 2 s @ 20 Hz)
        phase2 = py_trees.composites.Parallel(
            "H1_Phase2_Event",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ALL)
        if getattr(self, "_walker", None) and self._walker.is_alive:
            phase2.add_child(KeepWalkerMoving(self._walker, self._walk_dir,
                                              speed=4.0, ticks=40,
                                              name="H1_WalkerCross"))
        phase2.add_child(ForceEgoBrake(ego, ticks=40, brake=1.0,
                                       name="H1_EmergencyBrake"))
        seq.add_child(phase2)

        # Phase 3: resume driving
        seq.add_child(EgoBasicAgentBehavior(ego, dest, self.target_speed,
                                            ignore_tl=True, name="H1_Drive2"))
        return seq


class H2_HighwayCutIn(AdaptTrustScenario):
    """
    Town04 — NPC spawns 40 m behind ego in adjacent lane, catches up, then cuts in.
    Modeled exactly on srunner/scenarios/cut_in.py:
      Phase 1a: WaypointFollower(NPC) + InTriggerDistanceToVehicle until NPC within 30 m
      Phase 1b: AccelerateToCatchUp until NPC within 5 m of ego
      Phase 2 : LaneChange(NPC) + ForceEgoBrake(ego) simultaneously
      Phase 3 : EgoBasicAgentBehavior resumes
    """

    duration        = 25.0
    target_speed    = 70.0
    critical_event  = "BRAKING"

    def _do_initialize_actors(self, world):
        bp_lib  = world.get_blueprint_library()
        car_bps = [b for b in bp_lib.filter("vehicle.*")
                   if b.get_attribute("number_of_wheels").as_int() == 4]
        bp = car_bps[0] if car_bps else bp_lib.filter("vehicle.*")[0]

        ego    = self._ego()
        ego_wp = world.get_map().get_waypoint(ego.get_location())

        # Find an adjacent same-direction driving lane from ego's current position
        left_wp  = ego_wp.get_left_lane()
        right_wp = ego_wp.get_right_lane()
        _used_left = (left_wp is not None and
                      left_wp.lane_type == carla.LaneType.Driving)
        adj_wp = left_wp if _used_left else right_wp
        if adj_wp is None or adj_wp.lane_type != carla.LaneType.Driving:
            self._npc = None
            self._npc_cut_direction = 'right'
            print("[H2] WARNING: No adjacent driving lane found")
            return

        # NPC cuts toward ego: if spawned in left lane → cuts RIGHT; if right lane → cuts LEFT
        self._npc_cut_direction = 'right' if _used_left else 'left'

        # Spawn NPC 40 m BEHIND ego in the adjacent lane so it can visibly catch up
        behind_wps = adj_wp.previous(40.0)
        spawn_wp   = behind_wps[0] if behind_wps else adj_wp

        t   = carla.Transform(spawn_wp.transform.location + carla.Location(z=0.5),
                              spawn_wp.transform.rotation)
        npc = world.try_spawn_actor(bp, t)

        self._npc = npc
        if npc:
            self.other_actors.append(npc)
            # Register with CarlaDataProvider so WaypointFollower / AccelerateToCatchUp
            # / InTriggerDistanceToVehicle can look up this actor's location + velocity
            CarlaDataProvider.register_actor(npc, t)
            CarlaDataProvider._carla_actor_pool[npc.id] = npc
            world.tick()
            CarlaDataProvider.on_carla_tick()
            print(f"[H2] NPC id={npc.id} spawned 40 m behind ego, "
                  f"cut_direction={self._npc_cut_direction}")
        else:
            print("[H2] WARNING: NPC spawn failed — ForceEgoBrake only")

    def _do_create_behavior(self):
        from srunner.scenariomanager.timer import TimeOut as TOut

        ego  = self._ego()
        npc  = getattr(self, "_npc", None)
        dest = self._dest(2000.0)
        cut_dir = getattr(self, "_npc_cut_direction", 'right')

        seq = py_trees.composites.Sequence("H2_HighwayCutIn")

        # ---- Phase 1: NPC catches up to within 5 m of ego ----
        # Mirrors cut_in.py:  just_drive (WaypointFollower until 30 m)
        #                  then accelerate (AccelerateToCatchUp until 5 m)
        phase1 = py_trees.composites.Parallel(
            "H2_Phase1_CatchUp",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        phase1.add_child(EgoBasicAgentBehavior(ego, dest, self.target_speed,
                                               ignore_tl=True, name="H2_EgoDrive"))
        if npc:
            npc_phase1 = py_trees.composites.Sequence("H2_NpcPhase1")

            # Step A: follow waypoints at 80 km/h until within 30 m of ego
            npc_drive = py_trees.composites.Parallel(
                "H2_NpcDrive",
                policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
            npc_drive.add_child(WaypointFollower(npc, 80.0, name="H2_NpcFollow"))
            npc_drive.add_child(InTriggerDistanceToVehicle(
                npc, ego, 30.0, name="H2_NpcDist30"))
            npc_phase1.add_child(npc_drive)

            # Step B: full throttle to close from 30 m → 5 m (AccelerateToCatchUp
            # gets current control and overrides only throttle, preserving steering)
            npc_phase1.add_child(AccelerateToCatchUp(
                npc, ego,
                throttle_value=1.0,
                delta_velocity=10,     # m/s faster than ego → ~106 km/h vs 70 km/h
                trigger_distance=5,
                max_distance=400,
                name="H2_NpcCatchUp"))

            phase1.add_child(npc_phase1)
        else:
            phase1.add_child(DriveDistance(ego, 80.0, name="H2_FallbackDist"))
        # Safety valve: proceed after 14 s even if NPC didn't catch up
        phase1.add_child(TOut(14.0, name="H2_Phase1Timeout"))
        seq.add_child(phase1)

        # ---- Phase 2: NPC cuts into ego lane + ego emergency-brakes ----
        phase2 = py_trees.composites.Parallel(
            "H2_Phase2_CutIn",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ALL)
        if npc:
            phase2.add_child(DirectLaneChange(
                npc,
                direction=cut_dir,
                speed_mps=self.target_speed / 3.6,   # keep near-highway speed
                name="H2_LaneChange"))
        phase2.add_child(ForceEgoBrake(ego, ticks=40, brake=1.0,
                                       name="H2_EmergencyBrake"))
        seq.add_child(phase2)

        # ---- Phase 3: resume ----
        seq.add_child(EgoBasicAgentBehavior(ego, dest, self.target_speed,
                                            ignore_tl=True, name="H2_Resume"))
        return seq


class H3_RedLightRunner(AdaptTrustScenario):
    """
    Town03 — NPC runs red from cross street into intersection; ego hard-brakes 2 s.
    Modeled on srunner/scenarios/opposite_vehicle_taking_priority.py:
      - NPC spawned underground on a perpendicular road, physics disabled
      - Trigger: InTriggerDistanceToLocation fires when ego is 20 m from junction
      - NPC surfaces via ActorTransformSetter, then drives through at constant velocity
        using ConstantVelocityAgentBehavior (ignore_vehicles + ignore_traffic_lights)
      - Ego emergency-brakes simultaneously (ForceEgoBrake)
    """

    duration        = 22.0
    target_speed    = 40.0
    freeze_tls      = True   # all green so ego can approach freely
    critical_event  = "BRAKING"

    def _do_initialize_actors(self, world):
        bp_lib  = world.get_blueprint_library()
        car_bps = [b for b in bp_lib.filter("vehicle.*")
                   if b.get_attribute("number_of_wheels").as_int() == 4]
        bp = car_bps[0] if car_bps else bp_lib.filter("vehicle.*")[0]

        ego    = self._ego()
        ego_wp = world.get_map().get_waypoint(ego.get_location())

        # Walk forward 1 m at a time until we find the junction boundary (max 100 m)
        walk_wp = ego_wp
        junction_entry_wp = None
        for _ in range(100):
            nxt = walk_wp.next(1.0)
            if not nxt:
                break
            walk_wp = nxt[0]
            if walk_wp.is_junction:
                junction_entry_wp = walk_wp
                break

        if junction_entry_wp is None:
            self._runner_npc        = None
            self._npc_spawn_t       = None
            self._npc_target_loc    = None
            self._trigger_loc       = None
            print("[H3] WARNING: No junction found ahead of ego within 100 m")
            return

        junction     = junction_entry_wp.get_junction()
        ego_road_id  = ego_wp.road_id
        print(f"[H3] Junction id={junction.id}, entry road_id={junction_entry_wp.road_id}")

        # Find a cross-road entry waypoint inside this junction (different road than ego)
        cross_entry_wp = None
        npc_target_loc = None
        for wp_pair in junction.get_waypoints(carla.LaneType.Driving):
            candidate = wp_pair[0]
            if candidate.road_id == ego_road_id:
                continue
            # Back up 30 m on the cross road to get outside the junction
            prev_wps = candidate.previous(30.0)
            if not prev_wps or prev_wps[0].is_junction:
                continue
            cross_entry_wp = prev_wps[0]
            # Target: 40 m past junction entry (NPC drives fully through)
            fwd_wps = candidate.next(40.0)
            npc_target_loc = (fwd_wps[0].transform.location
                              if fwd_wps else candidate.transform.location)
            break

        if cross_entry_wp is None:
            self._runner_npc        = None
            self._npc_spawn_t       = None
            self._npc_target_loc    = None
            self._trigger_loc       = None
            print("[H3] WARNING: No cross-road found in junction")
            return

        # Trigger ego brake when it's 20 m from the junction entry
        self._trigger_loc = junction_entry_wp.transform.location

        # Spawn NPC below ground with physics disabled — ActorTransformSetter surfaces it
        spawn_t = carla.Transform(
            cross_entry_wp.transform.location + carla.Location(z=0.5),
            cross_entry_wp.transform.rotation)
        underground_t = carla.Transform(
            cross_entry_wp.transform.location - carla.Location(z=500),
            cross_entry_wp.transform.rotation)

        npc = world.try_spawn_actor(bp, spawn_t)
        if npc is None:
            self._runner_npc     = None
            self._npc_spawn_t    = None
            self._npc_target_loc = None
            self._trigger_loc    = None
            print("[H3] WARNING: NPC spawn failed")
            return

        # Park NPC underground until trigger fires
        npc.set_simulate_physics(False)
        npc.set_transform(underground_t)

        self._runner_npc     = npc
        self._npc_spawn_t    = spawn_t
        self._npc_target_loc = npc_target_loc
        self.other_actors.append(npc)
        # Register with CarlaDataProvider so ConstantVelocityAgentBehavior can look
        # up the actor's location via CarlaDataProvider.get_location()
        CarlaDataProvider.register_actor(npc, underground_t)
        CarlaDataProvider._carla_actor_pool[npc.id] = npc
        world.tick()
        CarlaDataProvider.on_carla_tick()
        print(f"[H3] NPC id={npc.id} ready underground; "
              f"cross_road at {cross_entry_wp.transform.location}, "
              f"trigger at junction_entry {self._trigger_loc}")

    def _do_create_behavior(self):
        from srunner.scenariomanager.timer import TimeOut as TOut

        ego        = self._ego()
        npc        = getattr(self, "_runner_npc", None)
        dest       = self._dest(2000.0)
        trigger    = getattr(self, "_trigger_loc", None)
        npc_spawn  = getattr(self, "_npc_spawn_t", None)
        npc_target = getattr(self, "_npc_target_loc", None)

        seq = py_trees.composites.Sequence("H3_RedLightRunner")

        # ---- Phase 1: ego approaches junction; NPC waits underground ----
        # Ends when ego is within 20 m of junction entry OR 8 s timer fires
        phase1 = py_trees.composites.Parallel(
            "H3_Phase1_Approach",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        phase1.add_child(EgoBasicAgentBehavior(ego, dest, self.target_speed,
                                               ignore_tl=True, name="H3_EgoDrive"))
        if trigger:
            phase1.add_child(InTriggerDistanceToLocation(
                ego, trigger, 20.0, name="H3_JunctionDist"))
        phase1.add_child(TOut(8.0, name="H3_FallbackTimer"))
        seq.add_child(phase1)

        # ---- Phase 2: NPC surfaces + crosses at constant speed; ego brakes ----
        # SUCCESS_ON_ONE: ForceEgoBrake finishes in 2 s → phase ends; NPC keeps driving
        phase2 = py_trees.composites.Parallel(
            "H3_Phase2_Event",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)

        if npc and npc_spawn and npc_target:
            npc_seq = py_trees.composites.Sequence("H3_NpcRun")
            # Teleport NPC to road surface and re-enable physics
            npc_seq.add_child(ActorTransformSetter(npc, npc_spawn, physics=True,
                                                   name="H3_NpcSurface"))
            # Drive through intersection at 54 km/h ignoring everything
            npc_seq.add_child(ConstantVelocityAgentBehavior(
                npc, npc_target,
                target_speed=15.0,   # m/s → 54 km/h (aggressive runner)
                opt_dict={'ignore_vehicles': True, 'ignore_traffic_lights': True},
                name="H3_NpcCross"))
            phase2.add_child(npc_seq)

        phase2.add_child(ForceEgoBrake(ego, ticks=40, brake=1.0,
                                       name="H3_EmergencyBrake"))
        seq.add_child(phase2)

        # ---- Phase 3: resume ----
        seq.add_child(EgoBasicAgentBehavior(ego, dest, self.target_speed,
                                            ignore_tl=True, name="H3_Resume"))
        return seq


# ===========================================================================
# NEW SCENARIOS — S1–S5 (AdaptTrust invisible-trigger study)
# ===========================================================================

class S1_JaywalkingAdult(AdaptTrustScenario):
    """
    Town02 — adult pedestrian steps out from behind a parked car mid-block.
    Ego cruises at 25 km/h, soft-brakes to a stop, waits for pedestrian to
    clear, then resumes.

    Layout (top-down):
      Parked car : 28 m ahead of spawn, 2.5 m lateral (waypoint-snapped, occluder)
      Walker     : 30 m ahead of spawn, 4.0 m RIGHT (hidden behind parked car)
      Walker walks LEFT (-right_vector) at 1.4 m/s (casual adult pace)

    Timing (@ 20 Hz, 25 km/h = 6.94 m/s, measured CARLA decel at brake=0.65: ~2.07 m/s²):
      t= 0.0–2.0 s  Phase 1  warmup TOut(2s); ego covers ~13.9 m, gap to walker=16.1 m
      t= 2.0 s      Phase 2  ForceEgoBrake(0.65, 70 ticks=3.5s) simultaneous with
                             KeepWalkerMoving(1.4 m/s, 70 ticks=3.5s)
                             ego stops in ~3.4 s covering ~11.8 m → gap to walker ~4.3 m ✓
                             walker emerges from behind car at t≈2.7s (YOLO detects)
      t= 5.5 s      Phase 3  KeepWalkerMoving(1.4 m/s, 40 ticks=2s) walker clears lane
      t= 7.5 s      Phase 4  EgoBasicAgentBehavior resumes to t=20 s
    """

    duration     = 20.0
    target_speed = 25.0   # km/h

    # Preferred blueprints for the parked occluder car
    _PARKED_PREF = [
        "vehicle.toyota.prius",
        "vehicle.audi.tt",
        "vehicle.seat.leon",
        "vehicle.tesla.model3",
        "vehicle.chevrolet.impala",
    ]

    def _do_initialize_actors(self, world):
        bp_lib = world.get_blueprint_library()

        # Use the original map spawn point (index 0) as the fixed reference so
        # NPC/pedestrian always spawn at their correct world positions even when
        # the ego is started further back on the road.
        spawn_pts = world.get_map().get_spawn_points()
        ego_t = spawn_pts[0]
        fwd   = ego_t.get_forward_vector()
        right = ego_t.get_right_vector()

        # ----------------------------------------------------------------
        # Parked car — occluder on the right side of the road
        # Physics disabled so it stays perfectly still and doesn't roll.
        # Offset 2.5 m right places it against the kerb on Town02's ~4m road.
        # ----------------------------------------------------------------
        parked_bp = None
        for name in self._PARKED_PREF:
            bp = bp_lib.find(name)
            if bp:
                parked_bp = bp
                break
        if parked_bp is None:
            car_bps = [b for b in bp_lib.filter("vehicle.*")
                       if b.get_attribute("number_of_wheels").as_int() == 4]
            if car_bps:
                parked_bp = car_bps[0]

        self._parked_car = None
        if parked_bp:
            # LEFT kerb: +2.5 × right_vector (right.x ≈ -1 for northbound Town02,
            # so +2.5*right.x shifts the car ~2.5 m to the LEFT/west kerb).
            # Keep PARK_DIST ≤ 22 m — building wall blocks left-side spawns above ~25 m.
            PARK_DIST = 15.0
            origin_wp = world.get_map().get_waypoint(spawn_pts[0].location)
            park_wps  = origin_wp.next(PARK_DIST)
            if park_wps:
                wp      = park_wps[0]
                # Use the oncoming (left) lane centre — well-defined CARLA position
                # clear of the building wall that blocks kerb-offset spawns on left side.
                left_wp = wp.get_left_lane()
                if left_wp is None:
                    left_wp = wp          # fallback: same lane centre
                park_loc = carla.Location(
                    x=left_wp.transform.location.x,
                    y=left_wp.transform.location.y,
                    z=left_wp.transform.location.z + 0.3,
                )
                park_tf = carla.Transform(park_loc, left_wp.transform.rotation)
                npc     = world.try_spawn_actor(parked_bp, park_tf)
                if npc:
                    npc.set_simulate_physics(False)
                    npc.set_autopilot(False)
                    self._parked_car = npc
                    self.other_actors.append(npc)
                    CarlaDataProvider.register_actor(npc, park_tf)
                    CarlaDataProvider._carla_actor_pool[npc.id] = npc
                    print(f"[S1] Parked car ({parked_bp.id})  "
                          f"+{PARK_DIST:.0f}m fwd  left-lane  "
                          f"x={park_loc.x:.1f} y={park_loc.y:.1f}")
                else:
                    print(f"[S1] WARNING: parked car spawn failed — no occluder")
            else:
                print(f"[S1] WARNING: no waypoint at {PARK_DIST}m ahead — no occluder")

        # ----------------------------------------------------------------
        # Walker — adult pedestrian, hidden behind the parked car.
        # Spawned 4.0 m right so it clears the parked car's body (~1m half-width
        # + 2.5m offset = 3.5m edge), giving ~0.5m clearance before physics.
        # Walk direction is -right_vector (walks left, across the road).
        # ----------------------------------------------------------------
        walkers = list(bp_lib.filter("walker.pedestrian.*"))
        # Prefer adult blueprints — avoid known child IDs
        _CHILD = {"walker.pedestrian.0008", "walker.pedestrian.0012",
                  "walker.pedestrian.0014", "walker.pedestrian.0016"}
        adult_bps  = [b for b in walkers if b.id not in _CHILD]
        walker_bp  = adult_bps[0] if adult_bps else (walkers[0] if walkers else None)

        self._walker    = None
        self._walk_dir  = None
        if walker_bp is None:
            print("[S1] WARNING: no walker blueprint — scenario runs without pedestrian")
            return

        WALK_DIST = 22.0   # m ahead  (ego stops ~10m from spawn → ~12m gap to walker)
        WALK_SIDE = -8.0   # m left   (spawn on left side, walks right across road)
        walk_loc  = carla.Location(
            x=ego_t.location.x + WALK_DIST * fwd.x + WALK_SIDE * right.x,
            y=ego_t.location.y + WALK_DIST * fwd.y + WALK_SIDE * right.y,
            z=ego_t.location.z + 0.5,
        )
        # Walk direction: perpendicular RIGHT across the road (reversed path)
        self._walk_dir = carla.Vector3D(x=right.x, y=right.y, z=0.0)

        walker = world.try_spawn_actor(
            walker_bp,
            carla.Transform(walk_loc,
                            carla.Rotation(yaw=ego_t.rotation.yaw + 90)))
        self._walker = walker
        if walker:
            self.other_actors.append(walker)
            world.tick()
            CarlaDataProvider.on_carla_tick()
            print(f"[S1] Walker ({walker_bp.id})  "
                  f"+{WALK_DIST:.0f}m fwd  +{WALK_SIDE:.1f}m right  "
                  f"x={walk_loc.x:.1f} y={walk_loc.y:.1f}")
        else:
            print("[S1] WARNING: walker spawn failed")

    def _do_create_behavior(self):
        ego  = self._ego()
        dest = self._dest()
        seq  = py_trees.composites.Sequence("S1_JaywalkingAdult")

        # ---- Phase 1: ego drives until it is within 30 m of the pedestrian ----
        # Using distance trigger instead of fixed timer so it works regardless
        # of how far back the ego spawns.
        walker_loc = (self._walker.get_location()
                      if getattr(self, "_walker", None) and self._walker.is_alive
                      else ego.get_location())
        phase1 = py_trees.composites.Parallel(
            "S1_Phase1_Approach",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        phase1.add_child(EgoBasicAgentBehavior(ego, dest, self.target_speed,
                                               ignore_tl=True, name="S1_Drive1"))
        phase1.add_child(WaitUntilEgoClose(ego, walker_loc, distance=15.0,
                                           name="S1_ApproachTrigger"))
        seq.add_child(phase1)

        walker_alive = getattr(self, "_walker", None) and self._walker.is_alive

        # ---- Phase 2: walker steps out + ego soft-brakes (3.5 s / 70 ticks) ----
        # brake=0.65, measured CARLA decel ≈ 2.07 m/s²
        # From 25 km/h (6.94 m/s): stops in ~3.4 s, covers ~11.8 m
        # Phase 1 covers 13.9 m → ego stops at ~25.7 m, walker at 30 m → gap ~4.3 m ✓
        # Walker at 1.4 m/s for 3.5 s: moves 4.9 m left (4.0 right → 0.9 m left of centre)
        phase2 = py_trees.composites.Parallel(
            "S1_Phase2_CrossingEvent",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ALL)
        phase2.add_child(ForceEgoBrake(ego, ticks=70, brake=0.65,
                                       name="S1_SoftBrake"))
        if walker_alive:
            phase2.add_child(KeepWalkerMoving(self._walker, self._walk_dir,
                                              speed=4, ticks=70,
                                              name="S1_WalkerStep"))
        seq.add_child(phase2)

        # ---- Phase 3: walker clears the lane (2 s / 40 ticks) ----
        # After Phase 2: walker is 0.9 m left of centre, needs ~1.6 m more to clear
        if walker_alive:
            seq.add_child(KeepWalkerMoving(self._walker, self._walk_dir,
                                           speed=4, ticks=40,
                                           name="S1_WalkerClears"))

        # ---- Phase 4: ego resumes, runs until duration (20 s) ----
        seq.add_child(EgoBasicAgentBehavior(ego, dest, self.target_speed,
                                            ignore_tl=True, name="S1_Resume"))
        return seq


# ---------------------------------------------------------------------------
# S2 — Sudden Stop + Evasive Lane Change
# ---------------------------------------------------------------------------

class S2_SuddenStopEvasion(AdaptTrustScenario):
    """
    Town04 — NPC car is 70 m ahead, driven by WaypointFollower at 40 km/h.
    Ego approaches at 60 km/h.  After 15 s (or when gap ≤ 20 m), the NPC
    emergency-stops — reason not visible from the front camera (classic AV
    unexplainability case).  Ego hard-brakes 60→20 km/h (~1.4 s), then
    DirectLaneChange swerves into the adjacent lane.  EgoBasicAgentBehavior
    resumes at 60 km/h through the Town04 highway curves.

    Trigger fired:
      BRAKING — brake=0.8 > 0.5, speed drop 60→20 km/h >> 5 km/h threshold
    """

    duration     = 30.0
    target_speed = 60.0

    def _do_initialize_actors(self, world):
        bp_lib  = world.get_blueprint_library()
        car_bps = [b for b in bp_lib.filter("vehicle.*")
                   if b.get_attribute("number_of_wheels").as_int() == 4]
        bp = car_bps[0] if car_bps else bp_lib.filter("vehicle.*")[0]

        ego_wp    = world.get_map().get_waypoint(self._ego().get_location())
        ahead_wps = ego_wp.next(70.0)
        if not ahead_wps:
            self._lead_npc = None
            print("[S2] WARNING: no waypoint 70 m ahead — no NPC spawned")
            return

        t = carla.Transform(
            ahead_wps[0].transform.location + carla.Location(z=0.5),
            ahead_wps[0].transform.rotation)
        npc = world.try_spawn_actor(bp, t)
        if not npc:
            self._lead_npc = None
            print("[S2] WARNING: NPC spawn failed")
            return

        self._lead_npc = npc
        self.other_actors.append(npc)
        CarlaDataProvider.register_actor(npc, t)
        CarlaDataProvider._carla_actor_pool[npc.id] = npc
        world.tick()
        CarlaDataProvider.on_carla_tick()
        # Note: no TM autopilot — NPC is driven by WaypointFollower in the
        # behavior tree (same pattern as H2_HighwayCutIn).
        loc = npc.get_transform().location
        print(f"[S2] Lead NPC id={npc.id} at x={loc.x:.1f} y={loc.y:.1f} "
              f"(70 m ahead, WaypointFollower @ 40 km/h)")

    def _do_create_behavior(self):
        from srunner.scenariomanager.timer import TimeOut as TOut

        ego = self._ego()
        npc = getattr(self, "_lead_npc", None)
        dest = self._dest(2000.0)

        # Compute a right-lane dest so Phase 4 BasicAgent routes around the
        # stopped NPC (which is in the original lane) rather than through it.
        world = CarlaDataProvider.get_world()
        dest_wp = world.get_map().get_waypoint(dest)
        right_wp = dest_wp.get_right_lane()
        phase4_dest = right_wp.transform.location if right_wp else dest

        seq = py_trees.composites.Sequence("S2_SuddenStopEvasion")

        # ---- Phase 1: both vehicles establish highway speed until gap ≤ 20 m ----
        # WaypointFollower drives NPC at 40 km/h (reliable, no TM dependency).
        # Starting gap ~70 m, closure rate ~20 km/h → triggers in ~9 s.
        phase1 = py_trees.composites.Parallel(
            "S2_Phase1_Approach",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        phase1.add_child(EgoBasicAgentBehavior(ego, dest, self.target_speed,
                                               ignore_tl=True, name="S2_Approach"))
        if npc:
            phase1.add_child(WaypointFollower(npc, 40.0 / 3.6, name="S2_NPCCruise"))
            phase1.add_child(InTriggerDistanceToVehicle(
                ego, npc, 20.0, name="S2_GapClose"))
        phase1.add_child(TOut(15.0, name="S2_Phase1Timeout"))
        seq.add_child(phase1)

        # ---- Phase 2: NPC emergency stop + ego hard-brakes simultaneously ----
        # From 60 km/h (16.67 m/s) at ~8 m/s² decel: 28 ticks → ~20 km/h.
        # NPC from 40 km/h at brake=1.0: stops in ~28 ticks (1.4 s) as well.
        # SUCCESS_ON_ONE fires when ego brake finishes; NPC gets persistent
        # brake=1.0 control keeping it stopped.
        brake_par2 = py_trees.composites.Parallel(
            "S2_Phase2_Brake",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        if npc:
            brake_par2.add_child(ForceEgoBrake(npc, ticks=60, brake=1.0,
                                               name="S2_NPCStop"))
        brake_par2.add_child(ForceEgoBrake(ego, ticks=18, brake=0.8,
                                           name="S2_EgoBrake"))
        seq.add_child(brake_par2)

        # ---- Phase 3: evasive lane change (~3.25 s) ----
        # steer=0.07 at ~20 km/h matches L2's rate for one lane-width lateral
        # shift. direction='right' = overtake (left) lane in Town04, per L2.
        seq.add_child(DirectLaneChange(ego,
                                       direction='right',
                                       speed_mps=20.0 / 3.6,
                                       steer=0.07,
                                       ticks_steer=35, ticks_straight=30,
                                       name="S2_EvasiveLaneChange"))

        # ---- Phase 4: resume in the evasion lane ----
        # Use phase4_dest (right-lane waypoint) so BasicAgent stays in the
        # evasion lane and does not route back through the stopped NPC.
        # TOut(12 s) fallback in case BasicAgent misbehaves after lane change.
        phase4 = py_trees.composites.Parallel(
            "S2_Phase4_Resume",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        phase4.add_child(EgoBasicAgentBehavior(ego, phase4_dest, self.target_speed,
                                               ignore_tl=True, ignore_vehicles=True,
                                               name="S2_Resume"))
        phase4.add_child(TOut(12.0, name="S2_Phase4Timeout"))
        seq.add_child(phase4)

        return seq


# ---------------------------------------------------------------------------
# S4 — Emergency Vehicle Pull-Over
# ---------------------------------------------------------------------------

class S4_EmergencyVehiclePullOver(AdaptTrustScenario):
    """
    Town02 — Corner-first design (run 1 update).

    Layout:
      Ego        : spawn[0] (x≈-7.5, y≈142), heading north.
      Ambulance  : spawns ~50 m behind ego (south of spawn[0]).
      Parked car : ~60 m ahead of ego along road, offset ~3 m right onto the
                   footpath — visible in front camera as ego approaches; the
                   parked car is what limits/motivates where ego stops on the
                   footpath.

    Phases:
      Phase 0 (28 s): Ego + ambulance both drive north at 25 km/h through
              Town02 junctions to the final eastbound straight (y≈240).
              Ambulance follows at the same speed — maintains ~50 m gap,
              visible in rear PiP the whole time.

      Phase 1 (≤20 s, trigger at 25 m gap): Ambulance accelerates to 60 km/h.
              Gap closes from ~50 m to 25 m (≈2.6 s at 35 km/h relative).
              Ambulance does NOT need to slow — by the time it reaches ego's
              original lane position, ego has already moved onto the footpath.

      Phase 2 (≤12 s):
              Ego — PullToCurb:
                Phase A (steer=+1.0, 40 ticks = 2 s): hard right drift with
                  zero brake; ego slides quickly south toward footpath.
                Phase B (steer=+0.80, brake=0.90, 80 ticks = 4 s): sustained
                  right steer + hard brake; ego stops deep on footpath, well
                  clear of the travel lane.
              Ambulance — AmbulanceDodgeAndPass:
                Drives at 60 km/h via BasicAgent (stays on road centre).
                When ego's lateral offset from road centre exceeds 1.5 m AND
                ambulance is within 20 m longitudinally, a brief left steer
                nudge (+0.14 for 25 ticks) makes the avoidance visually
                explicit: ambulance moves left of centre to clear the
                half-on-footpath ego.  BasicAgent routing then straightens it.
              WaitUntilAhead(x+20) ends phase once ambulance is 20 m clear.

      Phase 3 (≤8 s): Ego resumes with BasicAgent from curb position.
              Ambulance continues east at 60 km/h.

    Unexplainability: front camera shows clear road + the parked car ahead —
      the approaching ambulance is only visible in the rear-view mirror.

    Trigger: BRAKING
    """

    duration       = 48.0
    target_speed   = 25.0
    critical_event = "BRAKING"

    def _do_initialize_actors(self, world):
        bp_lib    = world.get_blueprint_library()
        emerg_bps = [b for b in bp_lib.filter("vehicle.*") if "ambulance" in b.id]
        car_bps   = [b for b in bp_lib.filter("vehicle.*")
                     if b.get_attribute("number_of_wheels").as_int() == 4]
        amb_bp = emerg_bps[0] if emerg_bps else (car_bps[0] if car_bps
                                                  else bp_lib.filter("vehicle.*")[0])

        # ---- Ambulance: 50 m behind ego ----
        # Town02 spawn[0] southbound road only extends ~31 m before the map
        # boundary.  Probe backwards in decreasing steps.  50 m is preferred;
        # fall back to whatever is available.
        ego_wp     = world.get_map().get_waypoint(self._ego().get_location())
        behind_wps = None
        for dist in [30.0, 25.0, 20.0, 15.0]:
            behind_wps = ego_wp.previous(dist)
            if behind_wps:
                break

        if not behind_wps:
            self._emerg_npc = None
            print("[S4] WARNING: no waypoint behind ego — ambulance skipped")
        else:
            t = carla.Transform(
                behind_wps[0].transform.location + carla.Location(z=0.5),
                behind_wps[0].transform.rotation)
            npc = world.try_spawn_actor(amb_bp, t)
            if npc:
                self._emerg_npc = npc
                self.other_actors.append(npc)
                CarlaDataProvider.register_actor(npc, t)
                CarlaDataProvider._carla_actor_pool[npc.id] = npc
                loc = npc.get_transform().location
                print(f"[S4] Ambulance ({amb_bp.id}) id={npc.id}  "
                      f"x={loc.x:.1f} y={loc.y:.1f}")
            else:
                self._emerg_npc = None
                print("[S4] WARNING: ambulance spawn failed")

        # ---- Parked car: ~60 m ahead of ego, offset ~3 m right (footpath) ----
        # Ego will pull right and stop on this footpath.  The parked car sits
        # ~60 m ahead of ego's starting point — visible in front camera before
        # and during the pull-over — motivating where ego stops.
        parked_bp = car_bps[1] if len(car_bps) > 1 else (car_bps[0] if car_bps
                                                           else amb_bp)
        ahead_wps = ego_wp.next(60.0)
        if ahead_wps:
            wp_a    = ahead_wps[0]
            right_v = wp_a.transform.get_right_vector()
            # 3.0 m right = onto footpath / shoulder
            park_loc = carla.Location(
                x=wp_a.transform.location.x + right_v.x * 3.0,
                y=wp_a.transform.location.y + right_v.y * 3.0,
                z=wp_a.transform.location.z + 0.3)
            park_t  = carla.Transform(park_loc, wp_a.transform.rotation)
            parked  = world.try_spawn_actor(parked_bp, park_t)
            if parked:
                self._parked_car = parked
                self.other_actors.append(parked)
                CarlaDataProvider.register_actor(parked, park_t)
                CarlaDataProvider._carla_actor_pool[parked.id] = parked
                # Freeze physics — car is completely static, no rolling
                parked.set_simulate_physics(False)
                print(f"[S4] Parked car ({parked_bp.id}) id={parked.id}  "
                      f"x={park_loc.x:.1f} y={park_loc.y:.1f}")
            else:
                self._parked_car = None
                print("[S4] WARNING: parked car spawn failed")
        else:
            self._parked_car = None
            print("[S4] WARNING: no waypoint 60 m ahead — parked car skipped")

        world.tick()
        CarlaDataProvider.on_carla_tick()

    def _do_create_behavior(self):
        from srunner.scenariomanager.timer import TimeOut as TOut

        ego   = self._ego()
        npc   = getattr(self, "_emerg_npc", None)
        world = self.world
        dest  = self._dest(500.0)

        # ----------------------------------------------------------------
        # FollowEgo — P-proportional gap controller.
        #
        # Uses BasicAgent for steering so the ambulance handles junctions
        # the same way ego does.  Destination is ego's live position,
        # refreshed every 10 ticks so routing adapts in near-real-time.
        # Speed is set by a proportional controller:
        #   speed = BASE_SPEED + KP * (actual_gap - TARGET_GAP)
        # Cap at MAX_SPEED so the ambulance can NEVER overtake ego.
        #
        # Result: ambulance stays at TARGET_GAP (30 m) throughout Phase 0,
        # surviving both junctions and always visible in the rear PiP.
        # ----------------------------------------------------------------
        class FollowEgo(AtomicBehavior):
            _TARGET_GAP   = 30.0   # m  — desired following distance
            _KP           = 1.8    # km/h per metre of gap error
            _BASE_SPEED   = 25.0   # km/h — matches ego cruise speed
            _MAX_SPEED    = 40.0   # km/h — hard cap; cannot overtake
            _UPDATE_TICKS = 10     # ticks between destination refreshes

            def __init__(inner, actor, ego_ref, name="FollowEgo"):
                super().__init__(name, actor)
                inner._ego_ref = ego_ref
                inner._agent   = None
                inner._tick    = 0

            def initialise(inner):
                from agents.navigation.basic_agent import BasicAgent
                inner._agent = BasicAgent(inner._actor,
                                          target_speed=inner._BASE_SPEED)
                inner._agent.ignore_traffic_lights(active=True)
                inner._agent.ignore_vehicles(active=True)
                inner._agent.set_destination(inner._ego_ref.get_location())
                inner._tick = 0

            def update(inner):
                if not (inner._actor and inner._actor.is_alive):
                    return py_trees.common.Status.SUCCESS
                inner._tick += 1

                ego_loc = inner._ego_ref.get_location()
                amb_loc = inner._actor.get_location()
                gap     = amb_loc.distance(ego_loc)

                # P-control: positive error → too far → speed up
                gap_err = gap - inner._TARGET_GAP
                spd     = inner._BASE_SPEED + inner._KP * gap_err
                spd     = max(5.0, min(inner._MAX_SPEED, spd))

                if inner._tick % inner._UPDATE_TICKS == 0:
                    inner._agent.set_destination(ego_loc)
                inner._agent.set_target_speed(spd)
                ctrl = inner._agent.run_step()
                inner._actor.apply_control(ctrl)
                return py_trees.common.Status.RUNNING

        # ----------------------------------------------------------------
        # PullToCurb v3 — natural footpath stop, calibrated steer.
        #
        # Calibration reference (from existing scenario comments):
        #   steer=+0.80, 3 s (60 ticks), 25 km/h → ~3 m lateral, ~16° yaw
        #   → lateral rate ≈ 1.0 m/s, turning radius ≈ 75 m.
        #
        # Phase A (50 ticks = 2.5 s):
        #   steer=+0.80, throttle=0, brake=0.
        #   Lateral displacement ≈ 0.8 m/s × 2.5 s = ~2.0 m (onto footpath).
        #   Yaw change ≈ (6.94×2.5/75) × 57.3 ≈ 13° — still pointing forward.
        #
        # Phase B (80 ticks = 4.0 s):
        #   steer=0.0, brake=0.85.
        #   Wheel straightened immediately — ego brakes to a full stop still
        #   roughly aligned with the road.  No continued arc into buildings.
        #
        # CARLA eastbound steer convention:
        #   positive steer → right (+y = south = footpath side)  ✓
        # ----------------------------------------------------------------
        class PullToCurb(AtomicBehavior):
            _STEER_A      = +0.80
            _STEER_TICKS  =  50    # 2.5 s at 20 fps → ~2 m lateral
            _BRAKE_B      =  0.85
            _BRAKE_TICKS  =  80    # 4.0 s → full stop on footpath

            def __init__(inner, actor, name="PullToCurb"):
                super().__init__(name, actor)
                inner._count = 0

            def initialise(inner):
                inner._count = 0

            def update(inner):
                if inner._count < inner._STEER_TICKS:
                    # Phase A: steer right, no brake — car drifts onto footpath
                    inner._actor.apply_control(carla.VehicleControl(
                        throttle=0.0, brake=0.0, steer=inner._STEER_A))
                else:
                    # Phase B: wheel straight, hard brake — stop on footpath
                    inner._actor.apply_control(carla.VehicleControl(
                        throttle=0.0, brake=inner._BRAKE_B, steer=0.0))
                inner._count += 1
                total = inner._STEER_TICKS + inner._BRAKE_TICKS
                return (py_trees.common.Status.SUCCESS
                        if inner._count >= total
                        else py_trees.common.Status.RUNNING)

        # ----------------------------------------------------------------
        # HoldBrake: keep ego fully braked — RUNNING forever.
        # ----------------------------------------------------------------
        class HoldBrake(AtomicBehavior):
            def __init__(inner, actor, name="HoldBrake"):
                super().__init__(name, actor)

            def update(inner):
                inner._actor.apply_control(carla.VehicleControl(
                    throttle=0.0, brake=1.0, steer=0.0))
                return py_trees.common.Status.RUNNING

        # ----------------------------------------------------------------
        # AmbulancePass — BasicAgent at 50 km/h + left dodge.
        #
        # BasicAgent routes along road centre, which is naturally LEFT of
        # ego stopped on the footpath — no steer needed to avoid.
        # The explicit dodge is a visual enhancement: a -0.15 steer nudge
        # for 30 ticks when the ambulance is alongside the stopped ego.
        #
        # CARLA eastbound steer sign (confirmed from S5v2 comment):
        #   negative steer = -y direction = LEFT (north, away from footpath)
        #   positive steer = +y direction = RIGHT (south, toward footpath)
        #
        # Lateral detection:
        #   ego.y - amb.y > LAT_THRESH means ego has moved south (footpath)
        #   while ambulance is still on the road.  POSITIVE when ego is
        #   correctly pulled over.  Previous code had this INVERTED.
        #
        # Timing:
        #   FollowEgo puts ambulance at 30 m when Phase 2 starts.
        #   Ambulance accelerates from 25 → 50 km/h; ego decelerates.
        #   Average relative closing speed ~15 km/h = 4.2 m/s.
        #   Time to close 30 m ≈ 7 s → ego has 7 s to complete pull-over
        #   (PullToCurb = 6.5 s total).  Ego is stopped before ambulance
        #   arrives.  No crash.
        # ----------------------------------------------------------------
        class AmbulancePass(AtomicBehavior):
            _SPEED_KMH   = 50.0
            _DODGE_STEER = -0.15   # LEFT on eastbound road (negative = -y = north)
            _DODGE_TICKS = 30
            _LAT_THRESH  = 1.0     # m: ego.y - amb.y must exceed this
            _LON_THRESH  = 15.0    # m: x-axis proximity for dodge to fire

            def __init__(inner, actor, ego_ref, dest, name="AmbulancePass"):
                super().__init__(name, actor)
                inner._ego_ref    = ego_ref
                inner._dest       = dest
                inner._agent      = None
                inner._dodge_tick = 0
                inner._dodging    = False
                inner._dodge_done = False

            def initialise(inner):
                from agents.navigation.basic_agent import BasicAgent
                inner._agent = BasicAgent(inner._actor,
                                          target_speed=inner._SPEED_KMH)
                inner._agent.ignore_traffic_lights(active=True)
                inner._agent.ignore_vehicles(active=True)
                inner._agent.set_destination(inner._dest)
                inner._dodge_tick = 0
                inner._dodging    = False
                inner._dodge_done = False

            def update(inner):
                if not (inner._actor and inner._actor.is_alive):
                    return py_trees.common.Status.SUCCESS

                ctrl = inner._agent.run_step()

                if not inner._dodge_done:
                    ego_loc = inner._ego_ref.get_location()
                    amb_loc = inner._actor.get_location()

                    # ego.y - amb.y > 0 when ego is south (footpath) of ambulance
                    lat_gap = ego_loc.y - amb_loc.y
                    # x-distance: fire when ambulance is within LON_THRESH of ego
                    lon_dist = abs(ego_loc.x - amb_loc.x)

                    if (lat_gap > inner._LAT_THRESH
                            and lon_dist < inner._LON_THRESH
                            and not inner._dodging):
                        inner._dodging    = True
                        inner._dodge_tick = 0
                        print(f"[S4] AmbulancePass dodge-left  "
                              f"lat={lat_gap:.2f} m  lon={lon_dist:.2f} m")

                    if inner._dodging and inner._dodge_tick < inner._DODGE_TICKS:
                        ctrl.steer = max(-1.0,
                                         min(1.0, ctrl.steer + inner._DODGE_STEER))
                        inner._dodge_tick += 1
                    elif inner._dodging:
                        inner._dodge_done = True
                        inner._dodging    = False

                inner._actor.apply_control(ctrl)
                return py_trees.common.Status.RUNNING

        # ----------------------------------------------------------------
        # WaitUntilAhead: Phase 2 ends when ambulance is margin m east
        # of stopped ego on the x-axis.
        # ----------------------------------------------------------------
        class WaitUntilAhead(AtomicBehavior):
            def __init__(inner, chaser, anchor, margin=20.0, name="WaitUntilAhead"):
                super().__init__(name, chaser)
                inner._anchor = anchor
                inner._margin = margin

            def update(inner):
                cx = inner._actor.get_location().x
                ax = inner._anchor.get_location().x
                return (py_trees.common.Status.SUCCESS
                        if cx > ax + inner._margin
                        else py_trees.common.Status.RUNNING)

        seq = py_trees.composites.Sequence("S4_EmergencyPullOver")

        # ---- Phase 0 (22 s): navigate to eastbound straight ----
        # At 25 km/h = 6.94 m/s, the route to the eastbound straight is
        # 49 + 48 + 49 = 146 m → ~21 s.  TOut(22) puts ego ~7 m onto
        # the straight before Phase 2 fires.
        # FollowEgo keeps ambulance at exactly 30 m behind ego throughout,
        # surviving both junctions — always visible in rear PiP.
        phase0 = py_trees.composites.Parallel(
            "S4_Phase0_Navigate",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        phase0.add_child(EgoBasicAgentBehavior(ego, dest, self.target_speed,
                                               ignore_tl=True,
                                               name="S4_P0_EgoDrive"))
        if npc:
            phase0.add_child(FollowEgo(npc, ego, name="S4_P0_FollowEgo"))
        phase0.add_child(TOut(22.0, name="S4_Phase0Timeout"))
        seq.add_child(phase0)

        # ---- Phase 2 (≤14 s): ego pulls over, ambulance passes ----
        # No Phase 1 — FollowEgo already placed ambulance at 30 m.
        # Ambulance accelerates from 25 → 50 km/h while ego decelerates
        # and moves right.  Average relative closing ~4 m/s → 7 s to
        # close 30 m — ego's PullToCurb (6.5 s) completes first.
        curb_hold = py_trees.composites.Sequence("S4_CurbHold")
        curb_hold.add_child(PullToCurb(ego, name="S4_PullToCurb"))
        curb_hold.add_child(HoldBrake(ego, name="S4_HoldBrake"))

        phase2 = py_trees.composites.Parallel(
            "S4_Phase2_PullOver",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        phase2.add_child(curb_hold)
        if npc:
            phase2.add_child(AmbulancePass(npc, ego, dest,
                                           name="S4_P2_AmbPass"))
            phase2.add_child(WaitUntilAhead(npc, ego, margin=20.0,
                                            name="S4_P2_AmbClear"))
        phase2.add_child(TOut(16.0, name="S4_Phase2Timeout"))
        seq.add_child(phase2)

        # ---- Phase 3 (<=12 s): ego reverses onto road, then follows ambulance ----
        # ReverseOntoRoad: 25 ticks (1.25 s) reverse at throttle=0.5 backs ego
        # off the footpath and onto the road surface.
        # Then BasicAgent takes over for the forward drive — scene cuts on TOut.
        class ReverseOntoRoad(AtomicBehavior):
            _TICKS = 25

            def __init__(inner, actor, name="ReverseOntoRoad"):
                super().__init__(name, actor)
                inner._count = 0

            def initialise(inner):
                inner._count = 0

            def update(inner):
                inner._actor.apply_control(carla.VehicleControl(
                    throttle=0.5, reverse=True, steer=0.0, brake=0.0))
                inner._count += 1
                return (py_trees.common.Status.SUCCESS
                        if inner._count >= inner._TICKS
                        else py_trees.common.Status.RUNNING)

        ego_resume = py_trees.composites.Sequence("S4_EgoResume")
        ego_resume.add_child(ReverseOntoRoad(ego, name="S4_Reverse"))
        ego_resume.add_child(EgoBasicAgentBehavior(ego, dest, self.target_speed,
                                                   ignore_tl=True,
                                                   ignore_vehicles=True,
                                                   name="S4_P3_Forward"))

        phase3 = py_trees.composites.Parallel(
            "S4_Phase3_Resume",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        phase3.add_child(ego_resume)
        if npc:
            phase3.add_child(EgoBasicAgentBehavior(npc, dest, 60.0,
                                                   ignore_tl=True,
                                                   ignore_vehicles=True,
                                                   name="S4_P3_AmbContinue"))
        phase3.add_child(TOut(12.0, name="S4_Phase3Timeout"))
        seq.add_child(phase3)

        return seq


# ---------------------------------------------------------------------------
# S5 — Partially-Hidden Cyclist
# ---------------------------------------------------------------------------

class S5_HiddenCyclist(AdaptTrustScenario):
    """
    Town02 — A slow cyclist (bicycle vehicle) rides 40 m ahead of ego at
    8 km/h.  A parked truck (right kerb, 20 m ahead) partially obscures the
    cyclist from the front camera until ego is within ~15 m.  Ego approaches
    at 30 km/h; a ForceEgoBrake fires the BRAKING trigger when the gap
    closes to ≤ 15 m.  After braking, BasicAgent resumes and overtakes the
    slow cyclist.

    Unexplainability: until the parked truck is passed, the bicycle is not
    clearly visible from the forward camera.  The AV brakes earlier than a
    human observer might expect.

    Triggers fired:
      BRAKING — brake=0.9 >> 0.5, speed drop >> 5 km/h
    """

    duration     = 25.0
    target_speed = 30.0

    _PARK_DIST = 20.0   # m ahead — parked truck (right kerb)
    _BIKE_DIST = 40.0   # m ahead — cyclist in lane centre

    def _do_initialize_actors(self, world):
        bp_lib  = world.get_blueprint_library()
        ego_wp  = world.get_map().get_waypoint(self._ego().get_location())

        # ---- Parked truck (right kerb) ----
        # In Town02 spawn[0], get_right_vector() points LEFT/west, so subtracting
        # 2.5× it moves the spawn point to the RIGHT/east kerb (proven in S1).
        # Truck is larger than sedan — better occlusion and won't block the lane.
        park_wps = ego_wp.next(self._PARK_DIST)
        if park_wps:
            park_wp  = park_wps[0]
            right    = park_wp.transform.get_right_vector()
            park_loc = carla.Location(
                x=park_wp.transform.location.x - 2.5 * right.x,
                y=park_wp.transform.location.y - 2.5 * right.y,
                z=park_wp.transform.location.z + 0.5)
            truck_bps = [b for b in bp_lib.filter("vehicle.*")
                         if "truck" in b.id or "firetruck" in b.id
                         or "carlacola" in b.id or "sprinter" in b.id]
            if not truck_bps:
                truck_bps = [b for b in bp_lib.filter("vehicle.*")
                             if b.get_attribute("number_of_wheels").as_int() == 4]
            truck_bp = truck_bps[0] if truck_bps else None
            if truck_bp:
                park_t = carla.Transform(park_loc, park_wp.transform.rotation)
                truck  = world.try_spawn_actor(truck_bp, park_t)
                if truck:
                    truck.set_simulate_physics(False)
                    truck.set_autopilot(False)
                    self._sedan = truck
                    self.other_actors.append(truck)
                    CarlaDataProvider.register_actor(truck, park_t)
                    CarlaDataProvider._carla_actor_pool[truck.id] = truck
                    print(f"[S5] Parked truck ({truck_bp.id}) id={truck.id} "
                          f"at x={park_loc.x:.1f} y={park_loc.y:.1f}")
                else:
                    self._sedan = None
                    print("[S5] WARNING: truck spawn failed — no occlusion")
            else:
                self._sedan = None
        else:
            self._sedan = None

        # ---- Cyclist (moving bicycle in lane centre) ----
        bike_wps = ego_wp.next(self._BIKE_DIST)
        if bike_wps:
            bike_wp  = bike_wps[0]
            bike_loc = bike_wp.transform.location + carla.Location(z=0.3)
            bike_bps = [b for b in bp_lib.filter("vehicle.*")
                        if any(k in b.id for k in ("crossbike", "omafiets",
                                                    "diamondback", "century"))]
            bike_bp  = bike_bps[0] if bike_bps else None
            if bike_bp:
                bike_t = carla.Transform(bike_loc, bike_wp.transform.rotation)
                bike   = world.try_spawn_actor(bike_bp, bike_t)
                if bike:
                    self._bike = bike
                    self.other_actors.append(bike)
                    CarlaDataProvider.register_actor(bike, bike_t)
                    CarlaDataProvider._carla_actor_pool[bike.id] = bike
                    print(f"[S5] Cyclist ({bike_bp.id}) id={bike.id} "
                          f"at x={bike_loc.x:.1f} y={bike_loc.y:.1f}")
                else:
                    self._bike = None
                    print("[S5] WARNING: bicycle spawn failed")
            else:
                self._bike = None
                print("[S5] WARNING: no bicycle blueprint")
        else:
            self._bike = None

    def _do_create_behavior(self):
        from srunner.scenariomanager.timer import TimeOut as TOut

        ego  = self._ego()
        dest = self._dest(2000.0)
        bike = getattr(self, "_bike", None)

        seq = py_trees.composites.Sequence("S5_HiddenCyclist")

        # ---- Phase 1: both ego and cyclist approach; trigger at 15 m gap ----
        # WaypointFollower drives cyclist at 8 km/h.
        # Closure rate 30−8=22 km/h; starting gap 40 m → 15 m gap in ~4.1 s.
        phase1 = py_trees.composites.Parallel(
            "S5_Phase1_Approach",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        phase1.add_child(EgoBasicAgentBehavior(ego, dest, self.target_speed,
                                               ignore_tl=True, name="S5_Approach"))
        if bike:
            phase1.add_child(WaypointFollower(bike, 8.0 / 3.6, name="S5_CyclistRide"))
            phase1.add_child(InTriggerDistanceToVehicle(
                ego, bike, 15.0, name="S5_CyclistClose"))
        phase1.add_child(TOut(8.0, name="S5_Phase1Timeout"))
        seq.add_child(phase1)

        # ---- Phase 2: emergency brake + keep cyclist at 8 km/h ----
        # WaypointFollower must continue here — without it the last throttle
        # command from Phase 1 persists and the cyclist accelerates to 35 km/h.
        phase2 = py_trees.composites.Parallel(
            "S5_Phase2_Brake",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        phase2.add_child(ForceEgoBrake(ego, ticks=40, brake=0.9,
                                       name="S5_EmergencyBrake"))
        if bike:
            phase2.add_child(WaypointFollower(bike, 8.0 / 3.6,
                                              avoid_collision=False,
                                              name="S5_CyclistBrakePhase"))
        seq.add_child(phase2)

        # ---- Phase 3: resume at 30 km/h, overtaking the cyclist ----
        # ignore_vehicles=True lets BasicAgent drive past the slow cyclist.
        # WaypointFollower keeps cyclist at 8 km/h so ego can overtake cleanly.
        phase3 = py_trees.composites.Parallel(
            "S5_Phase3_Resume",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        phase3.add_child(EgoBasicAgentBehavior(ego, dest, self.target_speed,
                                               ignore_tl=True, ignore_vehicles=True,
                                               name="S5_Resume"))
        if bike:
            phase3.add_child(WaypointFollower(bike, 8.0 / 3.6,
                                              avoid_collision=False,
                                              name="S5_CyclistResumePhase"))
        phase3.add_child(TOut(10.0, name="S5_Phase3Timeout"))
        seq.add_child(phase3)

        return seq


class S5v2_HiddenCyclist(AdaptTrustScenario):
    """
    Town10HD — spawn[1], heading east (+x).

    Layout:
      Ego     : spawn[1]  x=-67.3  y=28.0  heading east
      Truck   : 40 m ahead, 2.5 m right (shoulder) — past the cross-junction,
                parked static. x≈-27.3  y≈30.6
      Cyclist : 42 m ahead, 2.5 m right — spawned stationary BESIDE the truck,
                hidden from ego's forward camera behind truck body. x≈-25.3  y≈30.6

    Phases:
      Phase 0 (≤4 s): Ego drives east at 30 km/h. Cyclist is stationary beside
              the truck — not yet visible from the front camera.

      Phase 1 (merge, ~2 s): When ego has driven 20 m (DriveDistance), cyclist
              starts merging left into ego's lane using a fixed steer=-0.20
              (empirically: negative steer = -y = left on this eastbound road).
              Forward throttle keeps cyclist moving at ~5 km/h during merge.
              Ego continues at 30 km/h.

      Phase 2 (trigger): InTriggerDistanceToVehicle fires when ego-cyclist gap
              ≤ 18 m. ForceEgoBrake (brake=0.9, 40 ticks ≈ 2 s). Cyclist
              continues at 8 km/h via WaypointFollower.

      Phase 3a (deviation, ~2 s): Ego applies steer=-0.10 for 30 ticks to nudge
              left (-y) and clear the cyclist, then straightens for 20 ticks.
              Cyclist continues at 8 km/h.

      Phase 3b (resume, ≤8 s): BasicAgent resumes at 30 km/h with
              ignore_vehicles=True (ego is now laterally offset, safe to pass).
              Cyclist continues at 8 km/h.

    Unexplainability: cyclist was hidden beside the parked truck. When it
      merged into ego's lane the front camera showed nothing — AV braked before
      the cyclist was visible.

    Trigger: BRAKING
    """

    duration       = 22.0
    target_speed   = 30.0
    critical_event = "BRAKING"

    _TRUCK_DIST  = 38.0   # m — past cross-junction, clear road
    _BIKE_DIST   = 46.0   # m — 8 m ahead of truck centre, clear of truck body
    _SIDE_RIGHT  = 2.5    # m right of lane centre (shoulder)

    def _do_initialize_actors(self, world):
        bp_lib = world.get_blueprint_library()
        ego_wp = world.get_map().get_waypoint(self._ego().get_location())

        # ---- Parked truck on shoulder ----
        truck_wps = ego_wp.next(self._TRUCK_DIST)
        if truck_wps:
            twp   = truck_wps[0]
            right = twp.transform.get_right_vector()
            tloc  = carla.Location(
                x=twp.transform.location.x + self._SIDE_RIGHT * right.x,
                y=twp.transform.location.y + self._SIDE_RIGHT * right.y,
                z=twp.transform.location.z + 0.5)
            truck_bps = [b for b in bp_lib.filter("vehicle.*")
                         if "truck" in b.id or "carlacola" in b.id
                         or "sprinter" in b.id or "firetruck" in b.id]
            if not truck_bps:
                truck_bps = [b for b in bp_lib.filter("vehicle.*")
                             if b.get_attribute("number_of_wheels").as_int() == 4]
            truck_bp = truck_bps[0] if truck_bps else None
            if truck_bp:
                truck_t = carla.Transform(tloc, twp.transform.rotation)
                truck   = world.try_spawn_actor(truck_bp, truck_t)
                if truck:
                    truck.set_simulate_physics(False)
                    truck.set_autopilot(False)
                    self._truck = truck
                    self.other_actors.append(truck)
                    CarlaDataProvider.register_actor(truck, truck_t)
                    CarlaDataProvider._carla_actor_pool[truck.id] = truck
                    world.tick()
                    print(f"[S5v2] Truck ({truck_bp.id}) id={truck.id} "
                          f"x={tloc.x:.1f} y={tloc.y:.1f}")
                else:
                    self._truck = None
                    print("[S5v2] WARNING: truck spawn failed")
            else:
                self._truck = None
        else:
            self._truck = None

        # ---- Cyclist — spawned stationary beside truck, same lateral offset ----
        bike_wps = ego_wp.next(self._BIKE_DIST)
        if bike_wps:
            bwp   = bike_wps[0]
            right = bwp.transform.get_right_vector()
            bloc  = carla.Location(
                x=bwp.transform.location.x + self._SIDE_RIGHT * right.x,
                y=bwp.transform.location.y + self._SIDE_RIGHT * right.y,
                z=bwp.transform.location.z + 0.3)
            bike_bps = [b for b in bp_lib.filter("vehicle.*")
                        if any(k in b.id for k in ("crossbike", "omafiets",
                                                    "diamondback", "century"))]
            if not bike_bps:
                bike_bps = [b for b in bp_lib.filter("vehicle.*")
                            if "bike" in b.id or "bicycle" in b.id]
            bike_bp = bike_bps[0] if bike_bps else None
            if bike_bp:
                bike_t = carla.Transform(bloc, bwp.transform.rotation)
                bike   = world.try_spawn_actor(bike_bp, bike_t)
                if bike:
                    self._bike = bike
                    self.other_actors.append(bike)
                    CarlaDataProvider.register_actor(bike, bike_t)
                    CarlaDataProvider._carla_actor_pool[bike.id] = bike
                    world.tick()
                    print(f"[S5v2] Cyclist ({bike_bp.id}) id={bike.id} "
                          f"x={bloc.x:.1f} y={bloc.y:.1f}")
                else:
                    self._bike = None
                    print("[S5v2] WARNING: cyclist spawn failed")
            else:
                self._bike = None
                print("[S5v2] WARNING: no bicycle blueprint")
        else:
            self._bike = None

    def _do_create_behavior(self):
        from srunner.scenariomanager.timer import TimeOut as TOut

        ego  = self._ego()
        dest = self._dest(90.0)   # 90 m — stays on same straight, junction at 100 m
        bike = getattr(self, "_bike", None)

        # ----------------------------------------------------------------
        # Position estimates (all at 20 fps):
        #
        #   Ego spawn : x=-67.3  y=28.0  heading east (+x)
        #   Cyclist   : x=-21.3  y=30.5  (46 m ahead, 2.5 m right of centre)
        #   Steer conv: negative steer = -y = LEFT (away from footpath)
        #
        #   Phase 0 end (DriveDistance 25 m):
        #     Ego x=-42.3  Cyclist x=-21.3  euclidean gap=21.1 m
        #
        #   Phase 1 trigger (InTrigger 14 m):
        #     Fires at ~1.1 s — by then CyclistDart's 20-tick (1.0 s) steer
        #     phase has fully completed.
        #     Ego x≈-33.1  Cyclist x≈-18.8  y≈28.8 (in lane)  gap≈14 m
        #
        #   Phase 2 (ForceEgoBrake 0.9, 40 ticks = 2 s):
        #     Ego stops in ~1.0 s, travels 4.3 m  →  ego x≈-28.8
        #     Cyclist at ~16 km/h avg moves 8.9 m  →  cyclist x≈-9.9
        #     Minimum gap ≈ 14.9 m at t=0.5 s.  SAFE.
        #     Gap at end = 18.9 m (cyclist pulling away).
        #
        #   Phase 3 (EgoManeuver 35 ticks = 1.75 s):
        #     steer=-0.10, throttle=0.5 → ~1.6 m left (y: 28.0→26.4)
        #     Calibration ref: steer=0.04 at 22 km/h → 1 m / 1.5 s
        #     Ego x≈-23.9  Cyclist x≈-0.2  gap≈23.7 m
        #
        #   Phase 4 (EgoResumeStrght 60 ticks = 3 s):
        #     _STEER_CORR=+0.04 for 30 ticks → +0.91 m right → y≈27.3
        #     Ego resumes 30 km/h heading straight.  Cyclist far ahead.
        # ----------------------------------------------------------------

        # ----------------------------------------------------------------
        # CyclistDart — launches immediately with speed.
        # steer=-0.25 for 20 ticks (1 s): cyclist moves ~1.7 m left into lane.
        # throttle=0.9 from rest: cyclist reaches ~15 km/h during steer phase.
        # Then rides straight at 20 km/h via WaypointFollower in phases 2-4.
        # Negative steer = -y = LEFT on this eastbound road.
        # ----------------------------------------------------------------
        class CyclistDart(AtomicBehavior):
            _STEER       = -0.25
            _THROTTLE    =  0.9
            _TARGET_MPS  = 15.0 / 3.6
            _TICKS_STEER = 20    # 1.0 s steer left — ~1.7 m into lane
            _TICKS_STR   = 60    # 3.0 s ride straight (until WaypointFollower takes over)

            def __init__(self, actor, name="CyclistDart"):
                super().__init__(name, actor)
                self._count = 0

            def initialise(self):
                self._count = 0

            def update(self):
                if not (self._actor and self._actor.is_alive):
                    return py_trees.common.Status.SUCCESS
                v   = self._actor.get_velocity()
                spd = math.sqrt(v.x**2 + v.y**2 + v.z**2)
                thr = self._THROTTLE if spd < self._TARGET_MPS else 0.2
                st  = self._STEER if self._count < self._TICKS_STEER else 0.0
                self._actor.apply_control(
                    carla.VehicleControl(throttle=thr, steer=st, brake=0.0))
                self._count += 1
                total = self._TICKS_STEER + self._TICKS_STR
                return (py_trees.common.Status.SUCCESS
                        if self._count >= total
                        else py_trees.common.Status.RUNNING)

        # ----------------------------------------------------------------
        # EgoManeuver — steer left while accelerating, clearing cyclist.
        # steer=-0.10 for 35 ticks (1.75 s) at avg ~12 km/h.
        # Lateral displacement ≈ 1.6 m left (y: 28.0→26.4).
        # Ego stays in own lane — left edge, not crossing centre line.
        # throttle=0.5 keeps ego rolling forward at 10-18 km/h.
        # ----------------------------------------------------------------
        class EgoManeuver(AtomicBehavior):
            _STEER  = -0.04   # 0.35 m left at avg 10 km/h — well clear of divider
            _THR    =  0.50
            _TICKS  =  20     # 1.0 s

            def __init__(self, actor, name="EgoManeuver"):
                super().__init__(name, actor)
                self._count = 0

            def initialise(self):
                self._count = 0

            def update(self):
                if not (self._actor and self._actor.is_alive):
                    return py_trees.common.Status.SUCCESS
                self._actor.apply_control(carla.VehicleControl(
                    throttle=self._THR, steer=self._STEER, brake=0.0))
                self._count += 1
                return (py_trees.common.Status.SUCCESS
                        if self._count >= self._TICKS
                        else py_trees.common.Status.RUNNING)

        # ----------------------------------------------------------------
        # EgoResumeStrght — accelerate to 30 km/h and re-centre.
        # _STEER_CORR=+0.04 for 30 ticks corrects ~0.91 m rightward,
        # bringing ego from y≈26.4 back to y≈27.3 (near lane centre).
        # ----------------------------------------------------------------
        class EgoResumeStrght(AtomicBehavior):
            _TARGET_MPS = 30.0 / 3.6
            _TICKS      = 60
            _TICKS_CORR = 15     # ticks of right-correction steer
            _STEER_CORR = 0.02   # corrects ~0.2 m right — matches 0.35 m maneuver

            def __init__(self, actor, name="EgoResumeStrght"):
                super().__init__(name, actor)
                self._count = 0

            def initialise(self):
                self._count = 0

            def update(self):
                if not (self._actor and self._actor.is_alive):
                    return py_trees.common.Status.SUCCESS
                v   = self._actor.get_velocity()
                spd = math.sqrt(v.x**2 + v.y**2 + v.z**2)
                thr = 0.6 if spd < self._TARGET_MPS else 0.0
                st  = self._STEER_CORR if self._count < self._TICKS_CORR else 0.0
                self._actor.apply_control(
                    carla.VehicleControl(throttle=thr, steer=st, brake=0.0))
                self._count += 1
                return (py_trees.common.Status.SUCCESS
                        if self._count >= self._TICKS
                        else py_trees.common.Status.RUNNING)

        seq = py_trees.composites.Sequence("S5v2_HiddenCyclist")

        # ---- Phase 0: ego drives 25 m, cyclist stationary beside truck ----
        # At end: ego x=-42.3, cyclist x=-21.3, gap=21.1 m.
        phase0 = py_trees.composites.Parallel(
            "S5v2_Phase0_Approach",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        phase0.add_child(EgoBasicAgentBehavior(ego, dest, self.target_speed,
                                               ignore_tl=True, name="S5v2_P0_Drive"))
        phase0.add_child(DriveDistance(ego, 25.0, name="S5v2_P0_Dist"))
        seq.add_child(phase0)

        # ---- Phase 1: cyclist darts; ends when gap reaches 14 m ----
        # CyclistDart fires immediately: steer=-0.25, throttle=0.9.
        # InTrigger(14 m) fires at ~1.1 s — cyclist has fully completed
        # its steer phase (20 ticks = 1.0 s) and is in the lane (y≈28.8).
        # Ego is still at 30 km/h, gap=14 m — collision without braking in 1.7 s.
        phase1 = py_trees.composites.Parallel(
            "S5v2_Phase1_Dart",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        phase1.add_child(EgoBasicAgentBehavior(ego, dest, self.target_speed,
                                               ignore_tl=True, name="S5v2_P1_Drive"))
        if bike:
            phase1.add_child(CyclistDart(bike, name="S5v2_CyclistDart"))
            phase1.add_child(InTriggerDistanceToVehicle(
                ego, bike, 14.0, name="S5v2_GapTrigger"))
        phase1.add_child(TOut(3.0, name="S5v2_Phase1Timeout"))
        seq.add_child(phase1)

        # ---- Phase 2: ForceEgoBrake — sharp reactive stop ----
        # brake=0.9 for 40 ticks (2 s). Ego drops from 30 km/h to ~0 km/h.
        # Cyclist continues at 20 km/h via WaypointFollower — pulls away fast.
        # Minimum gap ≈ 14.9 m at t=0.5 s.  Verdict BRAKING fires here.
        phase2 = py_trees.composites.Parallel(
            "S5v2_Phase2_Brake",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        phase2.add_child(ForceEgoBrake(ego, ticks=40, brake=0.9,
                                       name="S5v2_EmergencyBrake"))
        if bike:
            phase2.add_child(WaypointFollower(bike, 20.0 / 3.6,
                                              avoid_collision=False,
                                              name="S5v2_P2_Cyclist"))
        seq.add_child(phase2)

        # ---- Phase 3: EgoManeuver — steer left, keep rolling ----
        # steer=-0.10, throttle=0.5 for 35 ticks (1.75 s).
        # Ego moves ~1.6 m left while accelerating from ~0 to ~15 km/h.
        # Cyclist is now 18.9 m ahead — no collision risk.
        phase3 = py_trees.composites.Parallel(
            "S5v2_Phase3_Maneuver",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        phase3.add_child(EgoManeuver(ego, name="S5v2_EgoManeuver"))
        if bike:
            phase3.add_child(WaypointFollower(bike, 20.0 / 3.6,
                                              avoid_collision=False,
                                              name="S5v2_P3_Cyclist"))
        seq.add_child(phase3)

        # ---- Phase 4: EgoResumeStrght — accelerate and re-centre ----
        # throttle=0.6 back to 30 km/h; steer=+0.04 for 30 ticks corrects
        # ~0.91 m rightward, bringing ego from y≈26.4 back to y≈27.3.
        # Cyclist is 23.7 m ahead and moving east — scene ends.
        phase4 = py_trees.composites.Parallel(
            "S5v2_Phase4_Resume",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        phase4.add_child(EgoResumeStrght(ego, name="S5v2_ResumeStrght"))
        if bike:
            phase4.add_child(WaypointFollower(bike, 20.0 / 3.6,
                                              avoid_collision=False,
                                              name="S5v2_P4_Cyclist"))
        seq.add_child(phase4)

        return seq


# ---------------------------------------------------------------------------
# Registry — maps scenario_id string → class
# ---------------------------------------------------------------------------

SCENARIO_REGISTRY = {
    "L1_GreenLightCruise":  L1_GreenLightCruise,
    "L2_SlowLeadOvertake":  L2_SlowLeadOvertake,
    "L3_NarrowStreetNav":   L3_NarrowStreetNav,
    "M1_YellowLightStop":   M1_YellowLightStop,
    "M2_CrosswalkYield":    M2_CrosswalkYield,
    "M3_HighwayMergeYield": M3_HighwayMergeYield,
    "H1_PedestrianDart":    H1_PedestrianDart,
    "H2_HighwayCutIn":      H2_HighwayCutIn,
    "H3_RedLightRunner":    H3_RedLightRunner,
    "S1_JaywalkingAdult":          S1_JaywalkingAdult,
    "S2_SuddenStopEvasion":        S2_SuddenStopEvasion,
    "S4_EmergencyVehiclePullOver": S4_EmergencyVehiclePullOver,
    "S5_HiddenCyclist":            S5_HiddenCyclist,
    "S5v2_HiddenCyclist":          S5v2_HiddenCyclist,
}

# Map: scenario_id → (map_name, spawn_index)
SCENARIO_MAP = {
    "L1_GreenLightCruise":  ("Town03", 1),
    "L2_SlowLeadOvertake":  ("Town04", 10),
    "L3_NarrowStreetNav":   ("Town02", 0),
    "M1_YellowLightStop":   ("Town03", 1),
    "M2_CrosswalkYield":    ("Town02", 0),
    "M3_HighwayMergeYield": ("Town04", 10),
    "H1_PedestrianDart":    ("Town02", 0),
    "H2_HighwayCutIn":      ("Town04", 10),
    "H3_RedLightRunner":    ("Town03", 1),
    "S1_JaywalkingAdult":          ("Town02", 0),
    "S2_SuddenStopEvasion":        ("Town04", 10),
    "S4_EmergencyVehiclePullOver": ("Town02", 0),
    "S5_HiddenCyclist":            ("Town02", 0),
    "S5v2_HiddenCyclist":          ("Town10HD", 1),
}
