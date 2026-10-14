"""Make mission_once.py never end a match by publishing nothing.

Rule 4.2(1): if the drone has not moved 5 min after the start signal the
round is over.  The 2026-10-12 color guard (md5 4b0ae381) returns None after
two mismatched answers, and a reply without a ```command block was always
dropped, so one bad LLM sample could cost the whole round (0 points) instead
of only the balloon stage (25 points).

This patch keeps the LLM as the only source of commands (rule: 九格 semantic
parsing is mandatory; no hand-written composite interface) and only changes
how its answers are checked and retried:
  * every answer is checked for a command block, known command names, and the
    balloon color named in the instruction;
  * up to MISSION_MAX_ATTEMPTS answers (default 3) within
    MISSION_RETRY_BUDGET_S seconds (default 60) are tried;
  * if none is fully valid, the closest answer is published verbatim instead of
    nothing, with a log line saying why.

Usage: python patch_mission_publish_fallback.py SOURCE OUTPUT [BACKUP_DIR]
"""
import hashlib
import pathlib
import shutil
import sys

EXPECTED_MD5 = "4b0ae381b683b7c38d30baf808ed1346"

OLD_START = "def expected_balloon_color(task):"
OLD_END = "\n\ndef main():\n"

NEW_BLOCK = '''# mission_publish_fallback_v1: check and retry LLM answers, never publish nothing.
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
        r"\\b(red|purple|blue)\\s+balloon\\b", task, re.IGNORECASE))
    return next(iter(colors)) if len(colors) == 1 else None


def command_balloon_colors(commands):
    """Return every hit_balloon target found in the command block."""
    return re.findall(r"(?m)^\\s*hit_balloon\\s*:\\s*([a-zA-Z]+)\\s*$", commands or "")


def command_problems(commands, expected):
    """List what is wrong with one answer; an empty list means publishable as-is."""
    if not commands:
        return ["no ```command block"]
    problems = []
    for line in commands.splitlines():
        cmd = line.strip()
        if not cmd or cmd in VALID_COMMANDS:
            continue
        m = re.fullmatch(r"hit_balloon\\s*:\\s*([a-zA-Z]+)", cmd)
        if not (m and m.group(1) in BALLOON_COLORS):
            problems.append("unknown command " + repr(cmd))
    if expected is not None:
        targets = command_balloon_colors(commands)
        if targets != [expected]:
            problems.append(f"color mismatch: task={expected}, commands={targets}")
    return problems


def retry_prompt(task, expected):
    hint = ("\\n请重新生成完整命令，放在一个 ```command 代码块中，每行一条，只能使用："
            "takeoff、cross_frame、detect_aruco、return_cross_frame、"
            "hit_balloon:red/purple/blue、land。")
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
        problems = command_problems(commands, expected)
        if not problems:
            return commands
        print(f"[命令校验] 第{attempt + 1}次生成不合格：{'; '.join(problems)}", flush=True)
        if commands:
            # Unknown commands are skipped by bt_ros, a wrong color only loses
            # the balloon stage: prefer the answer with fewer unknown commands.
            rank = (sum(p.startswith("unknown") for p in problems), len(problems))
            if best_rank is None or rank < best_rank:
                best, best_rank = commands, rank
        if time.monotonic() >= deadline:
            print("[命令校验] 重试时间预算用完", flush=True)
            break
    if best is not None:
        print("[命令校验] 没有完全合格的输出；按原样发布最接近的一次，"
              "避免开赛 5 分钟内无人机未动导致本轮结束", flush=True)
    return best
'''


def patch(source: bytes) -> bytes:
    if hashlib.md5(source).hexdigest() != EXPECTED_MD5:
        raise ValueError("mission_once.py MD5 differs from the 2026-10-12 color-guard version; no changes made")
    text = source.decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    text = text.replace("\r\n", "\n")
    if "mission_publish_fallback_v1" in text:
        raise ValueError("patch already present; no changes made")
    start = text.find(OLD_START)
    end = text.find(OLD_END, start)
    if start < 0 or end < 0 or text.count(OLD_START) != 1:
        raise ValueError("validation block not found exactly once; no changes made")
    text = text[:start] + NEW_BLOCK + text[end:]
    if text.count("\nimport re\n") != 1:
        raise ValueError("import anchor not found; no changes made")
    text = text.replace("\nimport re\n", "\nimport re\nimport time\n", 1)
    return text.replace("\n", newline).encode("utf-8")


if __name__ == "__main__":
    source = pathlib.Path(sys.argv[1])
    output = pathlib.Path(sys.argv[2])
    original = source.read_bytes()
    patched = patch(original)
    if len(sys.argv) > 3:
        backup_dir = pathlib.Path(sys.argv[3])
        backup_dir.mkdir(parents=True, exist_ok=False)
        shutil.copy2(source, backup_dir / "mission_once.py")
        (backup_dir / "restore.sh").write_text(
            "#!/usr/bin/env bash\nset -e\n"
            f"cp -p \"{(backup_dir / 'mission_once.py').resolve()}\" \"{source.resolve()}\"\n"
            f"md5sum \"{source.resolve()}\"  # expect {EXPECTED_MD5}\n",
            encoding="utf-8")
    output.write_bytes(patched)
    print(f"{EXPECTED_MD5} -> {hashlib.md5(patched).hexdigest()}")
