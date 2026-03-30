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

sys.path must include /home/meet/scenario_runner before importing this module.
"""

import sys
sys.path.insert(0, "/home/meet/scenario_runner")
sys.path.insert(0, "/home/meet/carla/PythonAPI/carla")

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
    """BasicAgentBehavior with guaranteed ignore_traffic_lights option."""

    def __init__(self, actor, target_location, target_speed, ignore_tl=True,
                 name="EgoBasicAgent"):
        super().__init__(actor, target_location=target_location,
                         target_speed=target_speed, name=name)
        self._ignore_tl = ignore_tl

    def initialise(self):
        super().initialise()
        self._agent.ignore_traffic_lights(active=self._ignore_tl)


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


class SafeLaneChange(LaneChange):
    """
    LaneChange with _pos_before_lane_change pre-seeded in initialise().

    The upstream LaneChange.update() crashes with NoneType if the actor has
    already drifted into the target lane before the first update() tick
    (which happens when AccelerateToCatchUp drove with steer=0 on a curve).
    Seeding the position here prevents the distance(Location, NoneType) error.
    """

    def initialise(self):
        super().initialise()
        if self._pos_before_lane_change is None:
            wp = CarlaDataProvider.get_map().get_waypoint(self._actor.get_location())
            self._pos_before_lane_change = wp.transform.location


class ForceLaneChange(AtomicBehavior):
    """One-shot: instruct TM to force NPC into the right lane (toward ego lane)."""

    def __init__(self, npc, tm, name="ForceLaneChange"):
        super().__init__(name, npc)
        self._tm = tm

    def update(self):
        if self._actor and self._actor.is_alive:
            self._tm.force_lane_change(self._actor, False)   # False = change RIGHT
        return py_trees.common.Status.SUCCESS


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
    target_speed   = 40.0    # km/h
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
    """Town03 — drive at 40 km/h through all-green lights for 20 s."""

    duration     = 20.0
    target_speed = 40.0

    def _do_create_behavior(self):
        return EgoBasicAgentBehavior(
            self._ego(), self._dest(), self.target_speed, ignore_tl=True,
            name="L1_Drive")


class L2_SlowLeadOvertake(AdaptTrustScenario):
    """Town04 — slow lead NPC at ~35 km/h; ego follows and decelerates. Speed adjustment is the key observable event."""

    duration     = 25.0
    target_speed = 60.0

    def _do_initialize_actors(self, world):
        bp_lib = world.get_blueprint_library()
        car_bps = [b for b in bp_lib.filter("vehicle.*")
                   if b.get_attribute("number_of_wheels").as_int() == 4]
        bp = car_bps[0] if car_bps else bp_lib.filter("vehicle.*")[0]

        ego_wp    = world.get_map().get_waypoint(self._ego().get_location())
        ahead_wps = ego_wp.next(30.0)
        if ahead_wps:
            t = ahead_wps[0].transform
            t.location.z += 0.5
            npc = world.try_spawn_actor(bp, t)
            if npc:
                self._lead_npc = npc
                self.other_actors.append(npc)
                # TM: drive at ~20 km/h (speed_difference is % below limit)
                tm = CarlaDataProvider.get_client().get_trafficmanager(CarlaDataProvider.get_traffic_manager_port())
                npc.set_autopilot(True, tm.get_port())
                tm.vehicle_percentage_speed_difference(npc, 60)  # 60% below limit ≈ 20 km/h
                tm.ignore_lights_percentage(npc, 100)
                tm.auto_lane_change(npc, False)

    def _do_create_behavior(self):
        return EgoBasicAgentBehavior(
            self._ego(), self._dest(), self.target_speed, ignore_tl=True,
            name="L2_Drive")


class L3_NarrowStreetNav(AdaptTrustScenario):
    """Town02 — navigate narrow urban streets at 20 km/h past 4 parked cars for 20 s."""

    duration     = 20.0
    target_speed = 20.0

    def _do_initialize_actors(self, world):
        bp_lib  = world.get_blueprint_library()
        car_bps = [b for b in bp_lib.filter("vehicle.*")
                   if b.get_attribute("number_of_wheels").as_int() == 4]
        bp = car_bps[0] if car_bps else bp_lib.filter("vehicle.*")[0]

        ego     = self._ego()
        ego_wp  = world.get_map().get_waypoint(ego.get_location())

        dist = 30.0
        for i in range(4):
            ahead_wps = ego_wp.next(dist)
            if not ahead_wps:
                dist += 15.0
                continue
            wp    = ahead_wps[0]
            right = wp.transform.get_right_vector()
            side  = 1.5 if i % 2 == 0 else -1.5   # alternate right/left
            loc   = carla.Location(
                x=wp.transform.location.x + side * right.x,
                y=wp.transform.location.y + side * right.y,
                z=wp.transform.location.z + 0.3,
            )
            t   = carla.Transform(loc, wp.transform.rotation)
            npc = world.try_spawn_actor(bp, t)
            if npc:
                npc.set_simulate_physics(False)
                npc.set_autopilot(False)
                self.other_actors.append(npc)
            dist += 15.0

    def _do_create_behavior(self):
        return EgoBasicAgentBehavior(
            self._ego(), self._dest(), self.target_speed, ignore_tl=True,
            name="L3_Drive")


# ===========================================================================
# MEDIUM criticality scenarios
# ===========================================================================

class M1_YellowLightStop(AdaptTrustScenario):
    """Town03 — TL turns Yellow at t=8 s; BasicAgent sees it and brakes gently."""

    duration     = 20.0
    target_speed = 40.0
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
        adj_wp = ego_wp.get_left_lane()
        if adj_wp is None or adj_wp.lane_type != carla.LaneType.Driving:
            adj_wp = ego_wp.get_right_lane()
        if adj_wp is None or adj_wp.lane_type != carla.LaneType.Driving:
            self._npc = None
            self._npc_cut_direction = 'right'
            print("[H2] WARNING: No adjacent driving lane found")
            return

        # NPC cuts toward ego: if adj is left lane → NPC cuts RIGHT; if right → cuts LEFT
        self._npc_cut_direction = 'right' if adj_wp == ego_wp.get_left_lane() else 'left'

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
            phase2.add_child(SafeLaneChange(
                npc,
                speed=None,                # keep current speed
                direction=cut_dir,
                distance_same_lane=5,
                distance_other_lane=300,
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
}
