"""Add few-shot examples the LLM has none of, to fix two 100%-reproducible
paraphrase failures found during the 2026-10-14 on-server test (20 phrasings
x 3 samples each, see v3_stability/reports/rule_compliance_20261014/):

  * "撞破蓝色球。" / "撞破红颜色的气球。" / "不要碰蓝色气球，扎破红色的气球。"
    -> model output the FULL six-step mission instead of one hit_balloon
    line, 9/9 times across these three phrasings. The prompt's only
    multi-step worked example is the one six-step walkthrough; every
    single-action balloon example uses near-identical wording ("去打X色气球"),
    so a phrasing even slightly off that pattern pulls the model toward the
    one complex example it has seen instead.
  * "返回起点并降落。" -> model added a spurious return_cross_frame before
    land, 3/3 times. The prompt's only landing example is the bare word
    "降落"; nothing disambiguates "返回起点" (go back to the start point) from
    "穿回方框" (cross back through the frame), so the model conflates them.

This patch is prompt engineering only -- it does not touch, fine-tune, or
replace the FM9G4B-V model itself (replacing the model voids the score per
rule 1.1), and officially this kind of fix is on us: per the supplementary QA
manual FAQ 5.7, "一条指令却执行多个任务...是语义理解出现偏差，需要自行去调整（微调）".

It appends three more few-shot examples after the existing six-step example,
in the same {1. 解释思路 / 2. 控制命令 ```command``` } format, using the
file's own CRLF line endings byte-for-byte.

Usage: python patch_mission_prompt_paraphrase_examples.py SOURCE OUTPUT [BACKUP_DIR]
"""
import hashlib
import pathlib
import shutil
import sys

EXPECTED_MD5 = "321f9b78eb3ad477172f37c70d8b921f"

ANCHOR = (
    "hit_balloon:red\n"
    "land\n"
    "```}"
)

NEW_EXAMPLES = """

用户: 撞破蓝色球
回答:
{1. 解释思路
用户要求打击蓝色气球，这是用户在这句话里要求的唯一动作，不额外补充起飞、穿框等步骤。
2. 控制命令
```command
hit_balloon:blue
```}

用户: 不要碰蓝色气球，扎破红色的气球
回答:
{1. 解释思路
用户只要求打击红色气球，并且明确排除蓝色气球，不输出其他颜色、不补充其他步骤。
2. 控制命令
```command
hit_balloon:red
```}

用户: 返回起点并降落
回答:
{1. 解释思路
用户要求返回起点并降落，这与"穿回方框"不同，不需要反向穿越方框，只执行降落指令即可返回起始点。
2. 控制命令
```command
land
```}"""


def patch(source: bytes) -> bytes:
    if hashlib.md5(source).hexdigest() != EXPECTED_MD5:
        raise ValueError("mission_prompt.txt MD5 differs from the 2026-10-12 deployed version; no changes made")
    text = source.decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    text = text.replace("\r\n", "\n")
    if "撞破蓝色球" in text:
        raise ValueError("patch already present; no changes made")
    if text.count(ANCHOR) != 1:
        raise ValueError("insertion anchor not found exactly once; no changes made")
    if not text.rstrip("\n").endswith(ANCHOR):
        raise ValueError("anchor is not at end of file as expected; no changes made")
    text = text.rstrip("\n") + NEW_EXAMPLES + "\n"
    return text.replace("\n", newline).encode("utf-8")


if __name__ == "__main__":
    source = pathlib.Path(sys.argv[1])
    output = pathlib.Path(sys.argv[2])
    original = source.read_bytes()
    patched = patch(original)
    if len(sys.argv) > 3:
        backup_dir = pathlib.Path(sys.argv[3])
        backup_dir.mkdir(parents=True, exist_ok=False)
        shutil.copy2(source, backup_dir / "mission_prompt.txt")
        (backup_dir / "restore.sh").write_text(
            "#!/usr/bin/env bash\nset -e\n"
            f"cp -p \"{(backup_dir / 'mission_prompt.txt').resolve()}\" \"{source.resolve()}\"\n"
            f"md5sum \"{source.resolve()}\"  # expect {EXPECTED_MD5}\n",
            encoding="utf-8")
    output.write_bytes(patched)
    print(f"{EXPECTED_MD5} -> {hashlib.md5(patched).hexdigest()}")
