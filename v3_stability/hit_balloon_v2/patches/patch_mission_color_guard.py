"""Add a fail-closed color check to the LLM command publisher.

Usage: python patch_mission_color_guard.py SOURCE OUTPUT [BACKUP_DIR]
The source must be the 2026-10-12 deployed mission_once.py snapshot.
When BACKUP_DIR is given, copy the original and emit restore.sh there.
"""
import hashlib
import pathlib
import shutil
import sys

EXPECTED_MD5 = "dcc050dd1daa1792a7312345932d0fcb"


def patch(source: bytes) -> bytes:
    if hashlib.md5(source).hexdigest() != EXPECTED_MD5:
        raise ValueError("mission_once.py source MD5 differs from the reviewed version")
    text = source.decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    text = text.replace("\r\n", "\n")
    marker = "\n\ndef main():\n"
    guard = '''

def expected_balloon_color(task):
    """Only enforce a color when the user explicitly names exactly one."""
    names = {"红": "red", "紫": "purple", "蓝": "blue"}
    colors = {names[m.group(1)] for m in re.finditer(r"([红紫蓝])色气球", task)}
    colors.update(m.group(1).lower() for m in re.finditer(
        r"\\b(red|purple|blue)\\s+balloon\\b", task, re.IGNORECASE))
    return next(iter(colors)) if len(colors) == 1 else None


def command_balloon_colors(commands):
    """Return every hit_balloon target found in the command block."""
    return re.findall(r"(?m)^\\s*hit_balloon\\s*:\\s*([a-zA-Z]+)\\s*$", commands or "")


def generate_validated_commands(model, tokenizer, base_msgs, task):
    expected = expected_balloon_color(task)
    for attempt in range(2):
        prompt = task if attempt == 0 else (
            task + "\\n请重新生成完整命令。任务明确要求打击" + expected +
            "色气球，命令必须且只能包含 hit_balloon:" + expected + "。")
        commands = generate_commands(model, tokenizer, base_msgs, prompt)
        if expected is None:
            return commands
        targets = command_balloon_colors(commands)
        if targets == [expected]:
            return commands
        print(f"[颜色校验] 第{attempt + 1}次生成不匹配：任务={expected}, 命令={targets}；拒绝发布", flush=True)
    return None
'''
    if text.count(marker) != 1:
        raise ValueError("main insertion point not unique")
    text = text.replace(marker, guard + marker)
    old = "commands = generate_commands(model, tokenizer, base_msgs, task)"
    if text.count(old) != 2:
        raise ValueError("command generation call count changed")
    text = text.replace(old, "commands = generate_validated_commands(model, tokenizer, base_msgs, task)")
    return text.replace("\n", newline).encode("utf-8")


if __name__ == "__main__":
    source = pathlib.Path(sys.argv[1])
    output = pathlib.Path(sys.argv[2])
    original = source.read_bytes()
    patched = patch(original)
    if len(sys.argv) > 3:
        backup_dir = pathlib.Path(sys.argv[3])
        backup_dir.mkdir(parents=True, exist_ok=True)
        original_backup = backup_dir / "mission_once.py"
        if original_backup.exists() and original_backup.read_bytes() != original:
            raise ValueError("backup exists with different content")
        shutil.copy2(source, original_backup)
        template = pathlib.Path(__file__).with_name("restore_mission_color_guard.sh")
        restore = template.read_text(encoding="utf-8").replace(
            "/home/ubuntu/mission_color_guard_backup_20261012T1850/mission_once.py",
            str(original_backup.resolve()))
        (backup_dir / "restore.sh").write_text(restore, encoding="utf-8")
    output.write_bytes(patched)
    print(f"{EXPECTED_MD5} -> {hashlib.md5(output.read_bytes()).hexdigest()}")
