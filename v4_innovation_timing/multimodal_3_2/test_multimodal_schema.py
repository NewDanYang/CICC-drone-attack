"""Offline contract checks for the strict FM9G4B-V image schema.

The test stubs only the imports needed to load mission_once.py; it never
loads a model, subscribes to ROS, or publishes a command.
"""
import importlib.util
import pathlib
import sys
import types

target = pathlib.Path(__file__).parent / "staging" / "mission_once.py"
for name in ("transformers", "torch", "rospy", "std_msgs", "std_msgs.msg"):
    sys.modules[name] = types.ModuleType(name)
sys.modules["transformers"].AutoModel = object
sys.modules["transformers"].AutoTokenizer = object
sys.modules["std_msgs.msg"].String = object

spec = importlib.util.spec_from_file_location("mission_once_multimodal", target)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

valid = '{"objects":[{"category":"balloon","color":"blue","bbox":[10,20,100,140]}]}'
assert module.parse_multimodal_answer(valid)[0]["bbox"] == [10, 20, 100, 140]
assert module.parse_multimodal_answer("```json\n" + valid + "\n```")[0]["color"] == "blue"
nested = '[[{"category":"balloon","color":"red","bbox":[10,20,100,140]}],[{"category":"frame","color":"unknown","bbox":[670,90,690,110]}]]'
assert len(module.parse_multimodal_answer(nested)) == 1
concatenated = '[{"category":"balloon","color":"red","bbox":[10,20,100,140]}], [{"category":"obstacle","color":"unknown","bbox":[200,100,300,200]}]'
assert len(module.parse_multimodal_answer(concatenated)) == 2

for invalid in (
    '{"objects":[{"category":"balloon","color":"blue","bbox":[10,20,100]}]}',
    '{"objects":[{"category":"balloon","color":"green","bbox":[10,20,100,140]}]}',
    '{"objects":[{"category":"balloon","color":"blue","bbox":[10,20,100,140],"score":1}]}',
):
    try:
        module.parse_multimodal_answer(invalid)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid schema accepted: " + invalid)

print("multimodal schema checks passed")
