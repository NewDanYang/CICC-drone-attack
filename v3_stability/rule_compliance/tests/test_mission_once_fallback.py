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
# A genuinely multi-step instruction: mentions both a non-balloon stage and the
# balloon stage, so single_action_problems() must NOT fire on it.
MULTI_STEP_TASK = "起飞，穿过框，识别二维码，再穿回来，去A区打{c}色气球，降落"


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
task = MULTI_STEP_TASK.format(c="红")
out, p = run(task, [FULL.format(c="red")])
check("valid first answer is published after 1 call", out == FULL.format(c="red") and len(p) == 1)

# 2. Wrong color, then right color: retried with a color hint.
task = MULTI_STEP_TASK.format(c="蓝")
out, p = run(task, [FULL.format(c="purple"), FULL.format(c="blue")])
check("wrong color is retried and fixed", out == FULL.format(c="blue") and len(p) == 2)
check("retry prompt names the color", "hit_balloon:blue" in p[1])

# 3. Wrong color on every attempt: still publishes (old code returned None).
task = MULTI_STEP_TASK.format(c="蓝")
out, p = run(task, [FULL.format(c="purple")] * 3)
check("all-wrong color still publishes the LLM answer verbatim", out == FULL.format(c="purple") and len(p) == 3)

# 4. No command block, then valid: retried (old code gave up immediately).
out, p = run("起飞", [None, "takeoff"])
check("missing command block is retried", out == "takeoff" and len(p) == 2)

# 5. Never a command block: nothing to publish (we must not invent commands).
out, p = run("起飞", [None, None, None])
check("no LLM command at all -> None, nothing hand-written", out is None and len(p) == 3)

# 6. Prefer the answer without unknown commands over one with them.
task = MULTI_STEP_TASK.format(c="红")
bad_cmd = "takeoff\nfly_to_balloon\nland"
out, p = run(task, [bad_cmd, FULL.format(c="purple"), None])
check("fewer unknown commands preferred as fallback", out == FULL.format(c="purple"))

# 7. Time budget stops retries early.
out, p = run("起飞", [None, "takeoff"], budget=0.0)
check("budget exhausted stops after first attempt", out is None and len(p) == 1)

# 8. Step-by-step single commands are valid.
for task, ans in [("起飞", "takeoff"), ("穿越方框", "cross_frame"), ("返航降落", "land")]:
    out, p = run(task, [ans])
    check(f"single-step {task} accepted", out == ans and len(p) == 1)

# --- v2: single_action_problems() regressions, from the 2026-10-14 on-server
# paraphrase test (v3_stability/reports/rule_compliance_20261014/samples.jsonl).
# These three phrasings got the full six-step mission or a spurious extra
# step 9/9, 9/9 and 3/3 times respectively, and v1's checks did not catch it
# because the color (when present) happened to be correct.

# 9. Balloon-only instruction: a full six-step answer must be rejected and
# retried, even though its color is correct -- this is the exact v1 blind spot.
out, p = run("撞破蓝色球。", [FULL.format(c="blue"), "hit_balloon:blue"])
check("single-action balloon instruction rejects a full six-step answer",
      out == "hit_balloon:blue" and len(p) == 2)

out, p = run("撞破红颜色的气球。", [FULL.format(c="red"), "hit_balloon:red"])
check("single-action balloon instruction (variant wording) retried",
      out == "hit_balloon:red" and len(p) == 2)

out, p = run("不要碰蓝色气球，扎破红色的气球。", [FULL.format(c="red"), "hit_balloon:red"])
check("single-action distractor-color instruction retried",
      out == "hit_balloon:red" and len(p) == 2)

# 10. If every attempt still expands to six steps, fall back to publishing the
# full sequence rather than nothing -- it still contains the right
# hit_balloon line, so it is strictly better than a stalled drone.
out, p = run("撞破蓝色球。", [FULL.format(c="blue")] * 3)
check("single-action balloon instruction still publishes on persistent over-generation",
      out == FULL.format(c="blue") and len(p) == 3)

# 11. Landing-only instruction: a spurious return_cross_frame must be rejected.
out, p = run("返回起点并降落。", ["return_cross_frame\nland", "land"])
check("landing-only instruction rejects a spurious return_cross_frame",
      out == "land" and len(p) == 2)

# 12. Multi-step instructions that legitimately mention both a balloon and
# another stage must NOT be second-guessed by single_action_problems().
task = MULTI_STEP_TASK.format(c="紫")
out, p = run(task, [FULL.format(c="purple")])
check("genuine multi-step instruction with a balloon stage is not flagged",
      out == FULL.format(c="purple") and len(p) == 1)

# 13. A genuine multi-step instruction that happens to end in landing must not
# be flagged by the landing-only rule either.
out, p = run("起飞，然后降落。", ["takeoff\nland"])
check("multi-step instruction ending in landing is not flagged as landing-only",
      out == "takeoff\nland" and len(p) == 1)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
