"""
一次性任务生成脚本 —— 输入完整的自然语言任务描述，大模型一次性生成所有指令并发送

用法:
    python3 mission_once.py "起飞，穿过框，识别二维码，再穿回来，去A区打红色气球，降落"
    python3 mission_once.py  (交互式输入)
"""
import sys
import os
import re
import time
import gc
from transformers import AutoModel, AutoTokenizer
import torch
import rospy
from std_msgs.msg import String


def load_model():
    """加载本地大模型"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    prompt_path = os.path.join(script_dir, "prompts", "mission_prompt.txt")
    model_dir = os.path.join(script_dir, "FM9G4B-V")

    knowledge_prompt = open(prompt_path, "r", encoding="utf-8").read()

    print("[1/3] 加载模型...", flush=True)
    model = AutoModel.from_pretrained(
        model_dir, trust_remote_code=True,
        attn_implementation='sdpa', torch_dtype=torch.bfloat16
    ).eval().cuda()
    tokenizer = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True)

    # 注入提示词
    print("[2/3] 注入提示词...", flush=True)
    msgs = [{"role": "user", "content": [knowledge_prompt]}]
    result = model.chat(image=None, msgs=msgs, tokenizer=tokenizer, sampling=True, stream=True)
    reply = ""
    for t in result:
        reply += t
    msgs.append({"role": "assistant", "content": [reply]})

    print("[3/3] 模型就绪。\n", flush=True)
    return model, tokenizer, msgs


def generate_commands(model, tokenizer, base_msgs, task_description):
    """向大模型发送任务描述，提取指令列表（每次只保留初始提示词，不累积历史）"""
    # 每次新建对话：初始提示词 + 本次任务
    msgs = base_msgs.copy()
    msgs.append({"role": "user", "content": [task_description]})

    result = model.chat(image=None, msgs=msgs, tokenizer=tokenizer, sampling=True, stream=True)
    content = ""
    for t in result:
        print(t, flush=True, end="")
        content += t
    print()

    # 推理完成后清理显存
    gc.collect()
    torch.cuda.empty_cache()

    # 提取 ```command ... ``` 代码块
    match = re.search(r"```(.*?)```", content, re.DOTALL)
    if not match:
        return None
    code = match.group(1)
    if code.startswith("command"):
        code = code[len("command"):]
    return code.strip()


# mission_publish_fallback_v1: check and retry LLM answers, never publish nothing.
VALID_COMMANDS = ("takeoff", "cross_frame", "detect_aruco", "return_cross_frame", "land")
BALLOON_COLORS = ("red", "purple", "blue")
MAX_ATTEMPTS = max(1, int(os.environ.get("MISSION_MAX_ATTEMPTS", "3")))
RETRY_BUDGET_S = float(os.environ.get("MISSION_RETRY_BUDGET_S", "60"))
COLOR_NAMES = {"red": "红", "purple": "紫", "blue": "蓝"}


def expected_balloon_color(task):
    """Only enforce a color when the instruction names exactly one."""
    names = {"红": "red", "紫": "purple", "蓝": "blue"}
    colors = {names[m.group(1)] for m in re.finditer(r"([红紫蓝])(?:颜?色)?(?:的)?气球", task)}
    colors.update(m.group(1).lower() for m in re.finditer(
        r"\b(red|purple|blue)\s+balloon\b", task, re.IGNORECASE))
    return next(iter(colors)) if len(colors) == 1 else None


def command_balloon_colors(commands):
    """Return every hit_balloon target found in the command block."""
    return re.findall(r"(?m)^\s*hit_balloon\s*:\s*([a-zA-Z]+)\s*$", commands or "")


# Catches the LLM expanding one requested action into the full six-step
# mission. Deliberately narrow: each rule only fires when the instruction
# mentions ONE family of stage keywords and none of the others, so a genuine
# multi-step instruction (which will mention more than one family) is never
# second-guessed. Evaluated against the ORIGINAL instruction text, never the
# retry-augmented prompt (which lists every command name, including the
# substring "aruco", and would otherwise always look like a multi-stage ask).
_BALLOON_MENTION = re.compile(r"(red|purple|blue|红|紫|蓝).{0,4}(balloon|气球|球)", re.IGNORECASE)
_OTHER_STAGE_FOR_BALLOON_ONLY = re.compile(
    r"起飞|升空|take\s*off|框|二维码|aruco|降落|land|穿|逆序|反向|原路", re.IGNORECASE)
_LAND_MENTION = re.compile(r"降落|land", re.IGNORECASE)
_OTHER_STAGE_FOR_LAND_ONLY = re.compile(
    r"起飞|升空|take\s*off|框|二维码|aruco|气球|balloon|球|穿|逆序|反向|原路", re.IGNORECASE)


def single_action_problems(commands, task):
    actual = [line.strip() for line in (commands or "").splitlines() if line.strip()]
    problems = []
    if _BALLOON_MENTION.search(task) and not _OTHER_STAGE_FOR_BALLOON_ONLY.search(task):
        if len(actual) != 1 or not actual[0].startswith("hit_balloon"):
            problems.append("steps_likely_extra: instruction names only the balloon stage")
    if _LAND_MENTION.search(task) and not _OTHER_STAGE_FOR_LAND_ONLY.search(task):
        if actual != ["land"]:
            problems.append("steps_likely_extra: instruction names only the landing stage")
    return problems


def balloon_command_missing(commands, task, expected):
    """1 when the task is clearly about hitting a balloon but the answer has
    no hit_balloon line at all (or, when a specific color IS known, the
    wrong one); 0 otherwise, including tasks that are not about a balloon.

    Deliberately keyed on _BALLOON_MENTION (any color word near "balloon"),
    not on `expected`: a distractor instruction like "不要碰蓝色气球，扎破
    红色的气球。" names two colors, so expected_balloon_color() returns None
    by design (ambiguous -> don't enforce a specific color) -- but the
    instruction is still unambiguously about hitting SOME balloon, and an
    answer with zero hit_balloon lines is strictly worse than one with any.
    """
    if not _BALLOON_MENTION.search(task):
        return 0
    targets = command_balloon_colors(commands)
    if not targets:
        return 1
    if expected is not None and expected not in targets:
        return 1
    return 0


def command_problems(commands, expected, task=""):
    """List what is wrong with one answer; an empty list means publishable as-is."""
    if not commands:
        return ["no ```command block"]
    problems = []
    for line in commands.splitlines():
        cmd = line.strip()
        if not cmd or cmd in VALID_COMMANDS:
            continue
        m = re.fullmatch(r"hit_balloon\s*:\s*([a-zA-Z]+)", cmd)
        if not (m and m.group(1) in BALLOON_COLORS):
            problems.append("unknown command " + repr(cmd))
    if expected is not None:
        targets = command_balloon_colors(commands)
        if targets != [expected]:
            problems.append(f"color mismatch: task={expected}, commands={targets}")
    problems.extend(single_action_problems(commands, task))
    return problems


def retry_prompt(task, expected):
    hint = ("\n请重新生成完整命令，放在一个 ```command 代码块中，每行一条，只能使用："
            "takeoff、cross_frame、detect_aruco、return_cross_frame、"
            "hit_balloon:red/purple/blue、land。只输出用户在这句话里明确要求的动作，"
            "不要自行补充没有提到的步骤。")
    if expected is not None:
        hint += ("任务明确要求打击" + COLOR_NAMES[expected] +
                 "色气球，命令必须且只能包含 hit_balloon:" + expected + "。")
    return task + hint


def generate_validated_commands(model, tokenizer, base_msgs, task):
    expected = expected_balloon_color(task)
    deadline = time.monotonic() + RETRY_BUDGET_S
    best, best_rank = None, None
    for attempt in range(MAX_ATTEMPTS):
        prompt = task if attempt == 0 else retry_prompt(task, expected)
        commands = generate_commands(model, tokenizer, base_msgs, prompt)
        problems = command_problems(commands, expected, task)
        if not problems:
            return commands
        print(f"[命令校验] 第{attempt + 1}次生成不合格：{'; '.join(problems)}", flush=True)
        if commands:
            # v3 (2026-10-15 real-model verification, distractor_color case):
            # rank by whether a balloon command is present FIRST, when the
            # task is about hitting a balloon at all. Before this, three
            # retries that all had exactly one problem ("steps_likely_extra")
            # ranked as ties, so the fallback kept whichever came first --
            # even when it was "detect_aruco; land" with no hit_balloon line
            # at all, while a later retry that merely had extra steps around
            # a correct "hit_balloon:red" lost the tie-break. Missing the
            # balloon command entirely costs the full 25-point stage; extra
            # steps around a correct one do not. balloon_command_missing()
            # keys on the task text itself (not on `expected`, which is
            # deliberately None for distractor instructions that name two
            # colors), so it still fires for exactly that case.
            # Unknown commands are skipped by bt_ros, a wrong color only loses
            # the balloon stage: prefer the answer with fewer unknown commands.
            rank = (balloon_command_missing(commands, task, expected),
                    sum(p.startswith("unknown") for p in problems), len(problems))
            if best_rank is None or rank < best_rank:
                best, best_rank = commands, rank
        if time.monotonic() >= deadline:
            print("[命令校验] 重试时间预算用完", flush=True)
            break
    if best is not None:
        print("[命令校验] 没有完全合格的输出；按原样发布最接近的一次，"
              "避免开赛 5 分钟内无人机未动导致本轮结束", flush=True)
    return best


def main():
    rospy.init_node("mission_once", anonymous=True)
    pub = rospy.Publisher("/mission_command", String, queue_size=10)
    rospy.sleep(1.0)

    model, tokenizer, base_msgs = load_model()

    # 如果命令行有参数，先执行一次
    if len(sys.argv) > 1:
        task = " ".join(sys.argv[1:])
        print(f"\n[任务] {task}")
        print("=" * 60)
        try:
            commands = generate_validated_commands(model, tokenizer, base_msgs, task)
            if commands:
                print(f"\n[生成的指令序列]\n{commands}\n")
                pub.publish(String(data=commands))
                rospy.loginfo("指令已发送到 /mission_command")
            else:
                print("\n[错误] 大模型未返回有效指令。")
        except RuntimeError as e:
            print(f"\n[错误] 推理失败: {e}")
            torch.cuda.empty_cache()

    # 持续等待用户输入（方便反复调试）
    while not rospy.is_shutdown():
        print("\n" + "=" * 60)
        print("请输入任务描述（输入 quit 退出）：")
        try:
            task = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n退出。")
            break
        if not task:
            continue
        if task.lower() in ("quit", "exit", "q"):
            print("退出。")
            break

        print(f"\n[任务] {task}")
        print("=" * 60)

        try:
            commands = generate_validated_commands(model, tokenizer, base_msgs, task)
        except RuntimeError as e:
            print(f"\n[错误] 推理失败: {e}")
            torch.cuda.empty_cache()
            continue
        if not commands:
            print("\n[错误] 大模型未返回有效指令。")
            continue

        print(f"\n[生成的指令序列]\n{commands}\n")
        pub.publish(String(data=commands))
        rospy.loginfo("指令已发送到 /mission_command")


if __name__ == "__main__":
    main()
