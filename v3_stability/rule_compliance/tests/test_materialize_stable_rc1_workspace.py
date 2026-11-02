import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

TOOL = Path(__file__).resolve().parents[1] / "tools/materialize_stable_rc1_workspace.py"
spec = importlib.util.spec_from_file_location("materialize", TOOL)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class MaterializeStableRC1Test(unittest.TestCase):
    def test_materializes_main_and_v2_sources_with_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            baseline = root / "official_baseline/catkin_ws/src/mission_pkg"
            v2 = root / "v2_time_optimization/working_source/src/mission_pkg"
            safety = root / "v1_safety_recovery/src/mission_pkg"
            detector = root / "official_baseline/catkin_ws/src/object_det"
            for path, text in ((detector / "package.xml", "detector package"),
                               (detector / "config/detection_params.yaml", "model: {}"),
                               (detector / "scripts/det_color_conda.sh", "#!/bin/sh"),
                               (root / "v3_stability/rule_compliance/deploy/aruco_detect_node.py", "aruco"),
                               (root / "v3_stability/rule_compliance/deploy/det_color.py", "detector"),
                               (baseline / "CMakeLists.txt", "main cmake"),
                               (baseline / "package.xml", "main package"),
                               (baseline / "src/base.cpp", "base"),
                               (root / "v3_stability/hit_balloon_v2/deployed_source/llm_mission.launch", "optimization/settle_timeout"),
                               (safety / "src/mavros_cnt.cpp", "safety"),
                               (safety / "include/mavros_cnt.h", "safety h"),
                               (v2 / "src/nodes/action/wait_for_stable_position.cpp", "wait"),
                               (v2 / "include/nodes/action/wait_for_stable_position.h", "wait h")):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            workspace = root.parent / (root.name + "-qualification")
            self.addCleanup(__import__('shutil').rmtree, workspace)
            package = workspace / "src/mission_pkg"
            (package / "old.txt").parent.mkdir(parents=True, exist_ok=True)
            (package / "old.txt").write_text("old", encoding="utf-8")
            output = root / "materialization.json"
            import subprocess, sys
            subprocess.run([sys.executable, str(TOOL), "--candidate-root", str(root),
                            "--workspace", str(workspace), "--underlay", str(root / 'underlay'),
                            "--output", str(output)], check=True)
            self.assertEqual((package / "CMakeLists.txt").read_text(), "main cmake")
            self.assertTrue((workspace / "src/object_det/config/detection_params.yaml").exists())
            self.assertEqual((package / "launch/llm_mission.launch").read_text(), "optimization/settle_timeout")
            data = json.loads(output.read_text())
            self.assertTrue(data["backup"])
            self.assertEqual((Path(data["backup"]) / "old.txt").read_text(), "old")
            self.assertFalse((package / 'old.txt').exists())
            self.assertNotIn(package.parent, Path(data['backup']).parents)


if __name__ == "__main__":
    unittest.main()
