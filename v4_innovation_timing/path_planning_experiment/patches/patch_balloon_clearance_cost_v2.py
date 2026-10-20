#!/usr/bin/env python3
"""Select the second and final parameter variant of the v1 cost function.

No C++ source is changed. The MD5 check prevents applying these ROS runtime
parameters to a different planner build.
"""

import argparse
import hashlib
from pathlib import Path
import subprocess

EXPECTED_V1_CPP = "c48a58affe333bfef509deba6b7ba43d"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", required=True)
    args = parser.parse_args()
    source = args.source_root / "src/planner/bspline_opt/src/bspline_optimizer.cpp"
    current = hashlib.md5(source.read_bytes()).hexdigest()
    if current != EXPECTED_V1_CPP:
        raise SystemExit(f"expected v1 C++ MD5 {EXPECTED_V1_CPP}, got {current}")
    values = {
        "/ego_planner_node/optimization/lambda_balloon_clearance": "2.0",
        "/ego_planner_node/optimization/balloon_clearance": "1.3",
    }
    for name, value in values.items():
        subprocess.run(["rosparam", "set", name, value], check=True)
        result = subprocess.run(["rosparam", "get", name], check=True,
                                text=True, capture_output=True)
        print(f"{name}={result.stdout.strip()}")


if __name__ == "__main__":
    main()
