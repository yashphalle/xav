"""
run_scene_only.py
Lightweight scenario tester — no YOLO, no sensors, no video recording.
Runs just the behavior tree tick loop so you can iterate on scenario logic fast.

Usage:
  python scripts/run_scene_only.py --scenario L2_SlowLeadOvertake
  python scripts/run_scene_only.py --scenario H2_HighwayCutIn --skip-map-reload
"""

import sys
import time
import math
import argparse
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_HOME = Path.home()
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_HOME / "scenario_runner"))
sys.path.insert(0, str(_HOME / "carla/PythonAPI/carla"))
sys.path.insert(0, str(_HOME / "carla/PythonAPI/carla/agents"))

import json

import py_trees

import carla
from srunner.scenariomanager.carla_data_provider import CarlaDataProvider
from srunner.scenariomanager.timer import GameTime

from scripts.scenarios.adaptrust_scenarios import (
    SCENARIO_REGISTRY, SCENARIO_MAP, AdaptTrustConfig,
)

FPS = 20


def main():
    parser = argparse.ArgumentParser(description="Scenario-only test (no recording).")
    parser.add_argument("--scenario", required=True, choices=sorted(SCENARIO_REGISTRY))
    parser.add_argument("--skip-map-reload", action="store_true")
    args = parser.parse_args()

    scenario_id = args.scenario
    map_name, spawn_index = SCENARIO_MAP[scenario_id]
    ScenCls = SCENARIO_REGISTRY[scenario_id]
    duration = getattr(ScenCls, "duration", 20.0)

    client = carla.Client("localhost", 2000)
    client.set_timeout(30.0)
    world  = client.get_world()

    # Map loading
    current_map = world.get_map().name.split("/")[-1]
    if args.skip_map_reload:
        print(f"[test] skip_map_reload — using current map ({current_map})")
    elif current_map != map_name:
        print(f"[test] Loading {map_name} ...")
        world = client.load_world(map_name)
        time.sleep(3.0)

    settings = world.get_settings()
    settings.synchronous_mode    = True
    settings.fixed_delta_seconds = 1.0 / FPS
    world.apply_settings(settings)

    tm = client.get_trafficmanager(8000)
    tm.set_synchronous_mode(True)

    CarlaDataProvider.set_client(client)
    CarlaDataProvider.set_world(world)
    CarlaDataProvider.set_traffic_manager_port(8000)

    for actor in world.get_actors().filter("vehicle.*"):
        actor.destroy()
    for actor in world.get_actors().filter("walker.*"):
        actor.destroy()
    world.tick()
    CarlaDataProvider.on_carla_tick()

    # Spawn ego, walked back 50 m for more approach road
    spawn_pts = world.get_map().get_spawn_points()
    spawn_t   = spawn_pts[spawn_index]
    wp = world.get_map().get_waypoint(spawn_t.location)
    prev_wps = wp.previous(50.0)
    if prev_wps:
        spawn_t = prev_wps[0].transform
        spawn_t.location.z += 0.3
        print(f"[test] Ego backed up 50 m to x={spawn_t.location.x:.1f} y={spawn_t.location.y:.1f}")
    else:
        print(f"[test] WARNING: no road behind spawn[{spawn_index}] — using original spawn")
    ego_bp    = world.get_blueprint_library().find("vehicle.tesla.model3")
    ego       = world.spawn_actor(ego_bp, spawn_t)
    CarlaDataProvider.register_actor(ego, spawn_t)
    CarlaDataProvider._carla_actor_pool[ego.id] = ego
    world.tick()
    CarlaDataProvider.on_carla_tick()
    print(f"[test] Spawned ego id={ego.id} at x={spawn_t.location.x:.1f} y={spawn_t.location.y:.1f}")

    cfg      = AdaptTrustConfig()
    scenario = ScenCls([ego], cfg, world)
    tree     = scenario.scenario_tree

    spectator = world.get_spectator()

    print(f"[test] Running {scenario_id} for {duration}s (no recording) ...")
    GameTime.restart()
    start_ts = world.get_snapshot().timestamp.elapsed_seconds
    tick     = 0

    # Full actor log — saved to actor_log.json at the end
    actor_log: list[dict] = []
    # Track last known position_rel per NPC id to detect pass events
    _npc_last_rel: dict[int, str] = {}

    # S5: build a role map so sedan/cyclist are clearly labelled in logs.
    # Key = actor id, value = short role string ("sedan", "cyclist", etc.)
    _npc_role: dict[int, str] = {}
    for a in scenario.other_actors:
        tid = a.type_id
        if any(k in tid for k in ("crossbike", "omafiets", "diamondback", "century", "bicycle")):
            _npc_role[a.id] = "CYCLIST"
        elif a.type_id.startswith("walker."):
            _npc_role[a.id] = "PED"
        elif any(k in tid for k in ("ambulance", "firetruck", "police")):
            _npc_role[a.id] = "EMERG"
        else:
            _npc_role[a.id] = "NPC"

    # S5: track occlusion state — is cyclist hidden behind parked sedan?
    _cyclist_occluded_last: bool | None = None

    try:
        while True:
            world.tick()
            snap = world.get_snapshot()
            CarlaDataProvider.on_carla_tick()
            GameTime.on_carla_tick(snap.timestamp)
            tree.tick_once()

            # Spectator camera: look BEHIND ego if any NPC is behind, else ahead.
            # This lets you see rear-approaching vehicles (e.g. S4 ambulance).
            t = ego.get_transform()
            yaw_rad = math.radians(t.rotation.yaw)
            has_rear_npc = any(
                (lambda fwd, dx, dy: fwd.x * dx + fwd.y * dy < 0)(
                    t.get_forward_vector(),
                    a.get_location().x - t.location.x,
                    a.get_location().y - t.location.y,
                )
                for a in scenario.other_actors if a.is_alive
            )
            if has_rear_npc:
                # Camera looks forward FROM behind — flipped 180° to face rearward
                cam_offset_x = +12.0 * math.cos(yaw_rad)
                cam_offset_y = +12.0 * math.sin(yaw_rad)
                cam_yaw      = t.rotation.yaw + 180.0
            else:
                cam_offset_x = -10.0 * math.cos(yaw_rad)
                cam_offset_y = -10.0 * math.sin(yaw_rad)
                cam_yaw      = t.rotation.yaw
            spectator.set_transform(carla.Transform(
                carla.Location(x=t.location.x + cam_offset_x,
                               y=t.location.y + cam_offset_y,
                               z=t.location.z + 6.0),
                carla.Rotation(pitch=-15.0, yaw=cam_yaw)))

            elapsed = snap.timestamp.elapsed_seconds - start_ts
            tick   += 1

            # --- Log ego every tick ---
            ego_loc = ego.get_location()
            ego_vel = ego.get_velocity()
            ego_spd = (ego_vel.x**2 + ego_vel.y**2 + ego_vel.z**2) ** 0.5 * 3.6
            ego_ctrl = ego.get_control()
            ego_entry = {
                "tick":    tick,
                "t":       round(elapsed, 3),
                "actor":   "ego",
                "id":      ego.id,
                "alive":   ego.is_alive,
                "x":       round(ego_loc.x, 3),
                "y":       round(ego_loc.y, 3),
                "z":       round(ego_loc.z, 3),
                "speed_kmh": round(ego_spd, 2),
                "throttle":  round(ego_ctrl.throttle, 3),
                "brake":     round(ego_ctrl.brake, 3),
                "steer":     round(ego_ctrl.steer, 3),
            }
            actor_log.append(ego_entry)

            # --- Log all NPC vehicles every tick ---
            for npc in scenario.other_actors:
                if not npc.is_alive:
                    actor_log.append({
                        "tick": tick, "t": round(elapsed, 3),
                        "actor": "npc", "id": npc.id, "alive": False,
                    })
                    continue
                loc  = npc.get_location()
                vel  = npc.get_velocity()
                spd  = (vel.x**2 + vel.y**2 + vel.z**2) ** 0.5 * 3.6
                ctrl      = npc.get_control() if hasattr(npc, "get_control") else None
                is_walker = npc.type_id.startswith("walker.")
                dist      = ego_loc.distance(loc)

                # Determine if NPC is ahead or behind ego using ego's forward vector
                ego_fwd  = ego.get_transform().get_forward_vector()
                to_npc_x = loc.x - ego_loc.x
                to_npc_y = loc.y - ego_loc.y
                dot      = ego_fwd.x * to_npc_x + ego_fwd.y * to_npc_y
                position_rel = "ahead" if dot >= 0 else "behind"

                role = _npc_role.get(npc.id, "walker" if is_walker else "npc")

                npc_entry = {
                    "tick":         tick,
                    "t":            round(elapsed, 3),
                    "actor":        role.lower(),
                    "role":         role,
                    "id":           npc.id,
                    "alive":        True,
                    "type":         npc.type_id,
                    "x":            round(loc.x, 3),
                    "y":            round(loc.y, 3),
                    "z":            round(loc.z, 3),
                    "speed_kmh":    round(spd, 2),
                    "dist_to_ego":  round(dist, 2),
                    "position_rel": position_rel,
                    "throttle":     round(ctrl.throttle, 3) if ctrl and hasattr(ctrl, "throttle") else None,
                    "brake":        round(ctrl.brake, 3)    if ctrl and hasattr(ctrl, "brake")    else None,
                    "steer":        round(ctrl.steer, 3)    if ctrl and hasattr(ctrl, "steer")    else None,
                }
                actor_log.append(npc_entry)

                # Detect pass event (behind → ahead transition) — vehicles only
                if not is_walker:
                    prev_rel = _npc_last_rel.get(npc.id)
                    if prev_rel == "behind" and position_rel == "ahead":
                        print(f"  *** [{role} id={npc.id}] "
                              f"PASSED EGO at t={elapsed:.2f}s  spd={spd:.1f}km/h ***")
                    _npc_last_rel[npc.id] = position_rel

                # Print every tick
                if is_walker:
                    print(f"  [{role} id={npc.id}] t={elapsed:.2f}s  {position_rel}  "
                          f"x={loc.x:.2f}  y={loc.y:.2f}  spd={spd:.1f}km/h  gap={dist:.1f}m")
                else:
                    thr   = ctrl.throttle if ctrl and hasattr(ctrl, "throttle") else 0.0
                    brake = ctrl.brake    if ctrl and hasattr(ctrl, "brake")    else 0.0
                    print(f"  [{role} id={npc.id}] "
                          f"t={elapsed:.2f}s  {position_rel}  x={loc.x:.2f}  y={loc.y:.2f}  "
                          f"spd={spd:.1f}km/h  gap={dist:.1f}m  "
                          f"thr={thr:.2f}  brake={brake:.2f}")

            # Walker logging is handled inside the other_actors loop above
            # (walkers that aren't in other_actors are irrelevant NPCs)

            # S5 occlusion detection: is the cyclist behind the parked sedan
            # from ego's point of view?  Sedan is stationary; cyclist moves.
            # Simple proxy: cyclist is "occluded" when its distance to ego is
            # GREATER than sedan's distance to ego (sedan is blocking the view).
            cyclist_actors = [a for a in scenario.other_actors
                              if a.is_alive and _npc_role.get(a.id) == "CYCLIST"]
            sedan_actors   = [a for a in scenario.other_actors
                              if a.is_alive and _npc_role.get(a.id) == "NPC"]
            if cyclist_actors and sedan_actors:
                cyclist_dist = ego_loc.distance(cyclist_actors[0].get_location())
                sedan_dist   = ego_loc.distance(sedan_actors[0].get_location())
                occluded = cyclist_dist > sedan_dist
                if occluded != _cyclist_occluded_last:
                    tag = "OCCLUDED (sedan blocking)" if occluded else "VISIBLE (past sedan)"
                    print(f"  >>> [S5] Cyclist now {tag}  "
                          f"t={elapsed:.2f}s  cyclist_gap={cyclist_dist:.1f}m  "
                          f"sedan_gap={sedan_dist:.1f}m")
                    _cyclist_occluded_last = occluded

            # Print ego summary every 2 seconds
            if tick % (FPS * 2) == 0:
                print(f"  [EGO] t={elapsed:.1f}s  speed={ego_spd:.1f}km/h  "
                      f"x={ego_loc.x:.1f}  y={ego_loc.y:.1f}  "
                      f"brake={ego_ctrl.brake:.2f}  throttle={ego_ctrl.throttle:.2f}")

            if elapsed >= duration:
                print(f"[test] Duration {duration}s reached — done.")
                break
            # Stop as soon as the scenario tree completes (SUCCESS or FAILURE).
            # Without this, tick_once() restarts the tree and behaviors like
            # ForceEgoBrake fire a second time.
            if tree.status in (py_trees.common.Status.SUCCESS,
                               py_trees.common.Status.FAILURE):
                print(f"[test] Scenario tree {tree.status.name} at t={elapsed:.2f}s — done.")
                break

    finally:
        settings.synchronous_mode    = False
        settings.fixed_delta_seconds = 0.0
        world.apply_settings(settings)
        for actor in scenario.other_actors:
            if actor.is_alive:
                actor.destroy()
        if ego.is_alive:
            ego.destroy()

        # Save full actor log
        log_path = _ROOT / "actor_log.json"
        with open(log_path, "w") as f:
            json.dump(actor_log, f, indent=2)
        print(f"[test] Actor log saved → {log_path}  ({len(actor_log)} entries)")
        print("[test] Cleaned up.")


if __name__ == "__main__":
    main()
