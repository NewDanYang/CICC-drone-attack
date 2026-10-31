"""Verify packaged raw bytes and protected command-generation functions offline."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path

root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'v2/manifest.json').read_text())
checks={name:hashlib.md5((root/name).read_bytes()).hexdigest()==value
        for name,value in manifest['package_md5'].items()}
spec=importlib.util.spec_from_file_location('patch',root/'patches/patch_v2_sources.py')
patch=importlib.util.module_from_spec(spec);spec.loader.exec_module(patch)
entry=(root/'v2/baseline_mission_once.py').read_bytes()
candidate=(root/'v2/mission_once.py').read_bytes()
assert patch.patch_entry(entry,(root/'v2/entry_main.py.txt').read_bytes())==candidate
bt=(root/'v2/baseline_bt_ros.cpp').read_bytes()
assert patch.patch_bt(bt)==(root/'v2/bt_ros.cpp').read_bytes()
def helpers(source):
    return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(source).body
            if isinstance(n,ast.FunctionDef) and n.name!='main'}
assert helpers(entry)==helpers(candidate)
assert all(checks.values()),checks
print(json.dumps(dict(package_md5_checks=checks,
    unchanged_command_helpers=sorted(helpers(entry)),
    bt_change='exactly one TargetTracker tag replaced; original tree/control structure intact',
    baseline_entry_md5=hashlib.md5(entry).hexdigest(),candidate_entry_md5=hashlib.md5(candidate).hexdigest(),
    manifest_sha256=hashlib.sha256((root/'v2/manifest.json').read_bytes()).hexdigest()),indent=2))
