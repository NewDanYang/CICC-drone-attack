"""Offline test of the mission_once.py retry/fallback logic.

The model, torch and ROS are stubbed; generate_commands is replaced by a
script of LLM answers.  Run: python test_mission_once_fallback.py
"""
import importlib.util
import pathlib
import sys
import types

HERE = pathlib.Path(__file__).resolve().parent
TARGET = HERE.parent / "deploy" / "mission_once.py"

for name in ("transformers", "torch", "rospy", "std_msgs", "std_msgs.msg"):
    sys.modules[name] = types.ModuleType(name)
sys.modules["transformers"].AutoModel = sys.modules["transformers"].AutoTokenizer = object
sys.modules["std_msgs.msg"].String = object

spec = importlib.util.spec_from_file_location("mission_once", TARGET)
mo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mo)

FULL = "takeoff\ncross_frame\ndetect_aruco\nreturn_cross_frame\nhit_balloon:{c}\nland"


def run(task, answers, budget=60.0):
    prompts = []
    queue = list(answers)

    def fake_generate(model, tokenizer, base_msgs, prompt):
        prompts.append(prompt)
        return queue.pop(0)

    mo.generate_commands = fake_generate
    mo.RETRY_BUDGET_S = budget
    return mo.generate_validated_commands(None, None, [], task), prompts


failures = []


def check(label, cond):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


# Color extraction from instruction phrasing we have not seen yet.
for task, want in [
    ("起飞，穿过框，识别二维码，再穿回来，去A区打红色气球，降落", "red"),
    ("扎破紫色的气球", "purple"),
    ("请撞破蓝颜色的气球", "blue"),
    ("打红气球", "red"),
    ("hit the Blue balloon", "blue"),
    ("不要碰蓝色气球，扎破红色气球", None),   # two colors: do not enforce
    ("起飞", None),
]:
    check(f"expected color {task!r} -> {want}", mo.expected_balloon_color(task) == want)

# 1. First answer valid: published, one call.
out, p = run("扎破红色气球", [FULL.format(c="red")])
check("valid first answer is published after 1 call", out == FULL.format(c="red") and len(p) == 1)

# 2. Wrong color, then right color: retried with a color hint.
out, p = run("扎破蓝色气球", [FULL.format(c="purple"), FULL.format(c="blue")])
check("wrong color is retried and fixed", out == FULL.format(c="blue") and len(p) == 2)
check("retry prompt names the color", "hit_balloon:blue" in p[1])

# 3. Wrong color on every attempt: still publishes (old code returned None).
out, p = run("扎破蓝色气球", [FULL.format(c="purple")] * 3)
check("all-wrong color still publishes the LLM answer verbatim", out == FULL.format(c="purple") and len(p) == 3)

# 4. No command block, then valid: retried (old code gave up immediately).
out, p = run("起飞", [None, "takeoff"])
check("missing command block is retried", out == "takeoff" and len(p) == 2)

# 5. Never a command block: nothing to publish (we must not invent commands).
out, p = run("起飞", [None, None, None])
check("no LLM command at all -> None, nothing hand-written", out is None and len(p) == 3)

# 6. Prefer the answer without unknown commands over one with them.
bad_cmd = "takeoff\nfly_to_balloon\nland"
out, p = run("扎破红色气球", [bad_cmd, FULL.format(c="purple"), None])
check("fewer unknown commands preferred as fallback", out == FULL.format(c="purple"))

# 7. Time budget stops retries early.
out, p = run("起飞", [None, "takeoff"], budget=0.0)
check("budget exhausted stops after first attempt", out is None and len(p) == 1)

# 8. Step-by-step single commands are valid.
for task, ans in [("起飞", "takeoff"), ("穿越方框", "cross_frame"), ("返航降落", "land")]:
    out, p = run(task, [ans])
    check(f"single-step {task} accepted", out == ans and len(p) == 1)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
