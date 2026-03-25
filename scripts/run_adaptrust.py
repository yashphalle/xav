"""
run_adaptrust.py
Entry-point for recording a single AdaptTrust scenario run.

Usage:
  python scripts/run_adaptrust.py --scenario H1_PedestrianDart --run 1
  python scripts/run_adaptrust.py --scenario L1_GreenLightCruise --run 1 --out /tmp/data

Available scenarios:
  LOW    : L1_GreenLightCruise, L2_SlowLeadOvertake, L3_NarrowStreetNav
  MEDIUM : M1_YellowLightStop, M2_CrosswalkYield, M3_HighwayMergeYield
  HIGH   : H1_PedestrianDart, H2_HighwayCutIn, H3_RedLightRunner

Requires:
  - CARLA server running: ./CarlaUE4.sh -quality-level=Low (dev)
  - conda activate carla-xav
"""

import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.adaptrust_runner import AdaptTrustRunner
from scripts.scenarios.adaptrust_scenarios import SCENARIO_REGISTRY, SCENARIO_MAP


def main():
    parser = argparse.ArgumentParser(
        description="Record one AdaptTrust scenario run.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(
            [f"  {sid:<24} map={SCENARIO_MAP[sid][0]}, spawn={SCENARIO_MAP[sid][1]}"
             for sid in sorted(SCENARIO_REGISTRY)]
        ),
    )
    parser.add_argument("--scenario", required=True,
                        choices=sorted(SCENARIO_REGISTRY),
                        help="Scenario ID to run")
    parser.add_argument("--run", type=int, default=1,
                        help="Run number (appended to output directory name)")
    parser.add_argument("--out", default=None,
                        help="Output root directory (default: data/scenarios/)")
    args = parser.parse_args()

    runner = AdaptTrustRunner(
        scenario_id=args.scenario,
        run_id=args.run,
        output_root=args.out,
    )
    result = runner.run()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
