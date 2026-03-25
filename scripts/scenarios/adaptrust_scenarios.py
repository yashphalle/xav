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
)
from srunner.scenariomanager.scenarioatomics.atomic_trigger_conditions import DriveDistance


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
        self._actor.apply_control(
            carla.VehicleControl(brake=self._brake, throttle=0.0))
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

def _far_waypoint(world, actor, dist_m=600.0):
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

    freeze_tls   = True
    target_speed = 40.0    # km/h
    duration     = 20.0    # seconds

    def __init__(self, ego_vehicles, config, world,
                 debug_mode=False, terminate_on_failure=False):
        self.timeout = self.duration + 5   # buffer so TimeOut doesn't end it too early
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
        return self._do_create_behavior()

    def _do_create_behavior(self):
        raise NotImplementedError

    def _create_test_criteria(self):
        return []

    # Convenience: destination far ahead from current ego position
    def _dest(self, dist_m=600.0):
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
    """Town04 — slow lead vehicle at 20 km/h 30 m ahead; ego approaches and slows."""

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
                tm = CarlaDataProvider.get_traffic_manager()
                npc.set_autopilot(True, tm.get_port())
                tm.vehicle_percentage_speed_difference(npc, 60)  # 60% below limit ≈ 20 km/h
                tm.ignore_lights_percentage(npc, 100)
                tm.auto_lane_change(npc, False)

    def _do_create_behavior(self):
        return EgoBasicAgentBehavior(
            self._ego(), self._dest(), self.target_speed, ignore_tl=True,
            name="L2_Drive")


class L3_NarrowStreetNav(AdaptTrustScenario):
    """Town02 — navigate narrow urban streets at 20 km/h for 20 s."""

    duration     = 20.0
    target_speed = 20.0

    def _do_create_behavior(self):
        return EgoBasicAgentBehavior(
            self._ego(), self._dest(400.0), self.target_speed, ignore_tl=True,
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

        # One-shot: flip nearest TL to Yellow
        seq.add_child(SetTLToState(ego, carla.TrafficLightState.Yellow,
                                   name="M1_SetYellow"))

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

        spawn_pts = world.get_map().get_spawn_points()
        ego_t     = spawn_pts[0]   # spawn_index 0 for Town02
        fwd       = ego_t.get_forward_vector()
        right     = ego_t.get_right_vector()

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
        dest = self._dest(400.0)
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
            spawn_wp = (left_wp
                        if left_wp and left_wp.lane_type == carla.LaneType.Driving
                        else ahead_wps[0])
            t = spawn_wp.transform
            t.location.z += 0.5
            npc = world.try_spawn_actor(bp, t)

        self._merge_npc = npc
        if npc:
            self.other_actors.append(npc)
            tm = CarlaDataProvider.get_traffic_manager()
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
        tm  = CarlaDataProvider.get_traffic_manager()
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

    duration     = 20.0
    target_speed = 30.0

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

        spawn_pts  = world.get_map().get_spawn_points()
        ego_t      = spawn_pts[0]   # spawn_index 0 (Town02)
        fwd        = ego_t.get_forward_vector()
        right      = ego_t.get_right_vector()

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
        dest = self._dest(400.0)
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
    """Town04 — NPC in left lane cuts into ego lane; ego emergency-brakes 2 s."""

    duration     = 25.0
    target_speed = 70.0

    def _do_initialize_actors(self, world):
        bp_lib  = world.get_blueprint_library()
        car_bps = [b for b in bp_lib.filter("vehicle.*")
                   if b.get_attribute("number_of_wheels").as_int() == 4]
        bp = car_bps[0] if car_bps else bp_lib.filter("vehicle.*")[0]

        ego_wp    = world.get_map().get_waypoint(self._ego().get_location())
        ahead_wps = ego_wp.next(15.0)
        npc = None
        if ahead_wps:
            left_wp  = ahead_wps[0].get_left_lane()
            spawn_wp = (left_wp
                        if left_wp and left_wp.lane_type == carla.LaneType.Driving
                        else ahead_wps[0])
            t = spawn_wp.transform
            t.location.z += 0.5
            npc = world.try_spawn_actor(bp, t)

        self._npc = npc
        if npc:
            self.other_actors.append(npc)
            tm = CarlaDataProvider.get_traffic_manager()
            npc.set_autopilot(True, tm.get_port())
            tm.ignore_lights_percentage(npc, 100)
            tm.vehicle_percentage_speed_difference(npc, -10)   # slightly faster than ego
            tm.auto_lane_change(npc, False)                    # prevent early random LC

    def _do_create_behavior(self):
        ego  = self._ego()
        dest = self._dest()
        tm   = CarlaDataProvider.get_traffic_manager()
        seq  = py_trees.composites.Sequence("H2_HighwayCutIn")

        # Phase 1: drive 30 m before triggering
        phase1 = py_trees.composites.Parallel(
            "H2_Phase1_Approach",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        phase1.add_child(EgoBasicAgentBehavior(ego, dest, self.target_speed,
                                               ignore_tl=True, name="H2_Drive1"))
        phase1.add_child(DriveDistance(ego, 30.0, name="H2_DistanceTrigger"))
        seq.add_child(phase1)

        # Phase 2: force NPC lane change + ego emergency-brakes
        npc = getattr(self, "_npc", None)
        phase2 = py_trees.composites.Parallel(
            "H2_Phase2_CutIn",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        if npc and npc.is_alive:
            phase2.add_child(ForceLaneChange(npc, tm, name="H2_NpcCutIn"))
        phase2.add_child(ForceEgoBrake(ego, ticks=40, brake=1.0,
                                       name="H2_EmergencyBrake"))
        seq.add_child(phase2)

        # Phase 3: resume
        seq.add_child(EgoBasicAgentBehavior(ego, dest, self.target_speed,
                                            ignore_tl=True, name="H2_Drive2"))
        return seq


class H3_RedLightRunner(AdaptTrustScenario):
    """Town03 — NPC runs red from cross street into intersection; ego hard-brakes 2 s."""

    duration     = 20.0
    target_speed = 40.0

    def _do_initialize_actors(self, world):
        bp_lib  = world.get_blueprint_library()
        car_bps = [b for b in bp_lib.filter("vehicle.*")
                   if b.get_attribute("number_of_wheels").as_int() == 4]
        bp = car_bps[0] if car_bps else bp_lib.filter("vehicle.*")[0]

        # Spawn NPC on the LEFT perpendicular road 30 m ahead of ego
        ego_wp    = world.get_map().get_waypoint(self._ego().get_location())
        ahead_wps = ego_wp.next(30.0)
        npc = None
        if ahead_wps:
            ahead_wp = ahead_wps[0]
            # Try to find a junction waypoint to spawn the cross-traffic NPC
            left_wp = ahead_wp.get_left_lane()
            if left_wp and left_wp.lane_type == carla.LaneType.Driving:
                t = left_wp.transform
                # Offset further left so it approaches from the side
                right = t.get_right_vector()
                t.location.x -= 20.0 * right.x
                t.location.y -= 20.0 * right.y
                t.location.z += 0.5
                npc = world.try_spawn_actor(bp, t)

        if npc is None:
            # Fallback: spawn on adjacent spawn point
            spawn_pts = world.get_map().get_spawn_points()
            if len(spawn_pts) > 5:
                npc = world.try_spawn_actor(bp, spawn_pts[5])

        self._runner_npc = npc
        if npc:
            self.other_actors.append(npc)
            tm = CarlaDataProvider.get_traffic_manager()
            npc.set_autopilot(True, tm.get_port())
            tm.ignore_lights_percentage(npc, 100)   # always runs red lights
            tm.vehicle_percentage_speed_difference(npc, -20)  # drives fast

    def _do_create_behavior(self):
        ego  = self._ego()
        dest = self._dest()
        seq  = py_trees.composites.Sequence("H3_RedLightRunner")

        # Phase 1: ego drives 20 m (approach intersection)
        phase1 = py_trees.composites.Parallel(
            "H3_Phase1_Approach",
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        phase1.add_child(EgoBasicAgentBehavior(ego, dest, self.target_speed,
                                               ignore_tl=True, name="H3_Drive1"))
        phase1.add_child(DriveDistance(ego, 20.0, name="H3_DistanceTrigger"))
        seq.add_child(phase1)

        # Phase 2: ego emergency-brakes 40 ticks (NPC continues autonomously via TM)
        seq.add_child(ForceEgoBrake(ego, ticks=40, brake=1.0,
                                    name="H3_EmergencyBrake"))

        # Phase 3: resume
        seq.add_child(EgoBasicAgentBehavior(ego, dest, self.target_speed,
                                            ignore_tl=True, name="H3_Drive2"))
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
    "L1_GreenLightCruise":  ("Town03", 0),
    "L2_SlowLeadOvertake":  ("Town04", 10),
    "L3_NarrowStreetNav":   ("Town02", 0),
    "M1_YellowLightStop":   ("Town03", 0),
    "M2_CrosswalkYield":    ("Town02", 0),
    "M3_HighwayMergeYield": ("Town04", 10),
    "H1_PedestrianDart":    ("Town02", 0),
    "H2_HighwayCutIn":      ("Town04", 10),
    "H3_RedLightRunner":    ("Town03", 0),
}
