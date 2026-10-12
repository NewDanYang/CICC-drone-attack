"""
一次性任务生成脚本 —— 输入完整的自然语言任务描述，大模型一次性生成所有指令并发送

用法:
    python3 mission_once.py "起飞，穿过框，识别二维码，再穿回来，去A区打红色气球，降落"
    python3 mission_once.py  (交互式输入)
"""
import sys
import os
import re
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


def expected_balloon_color(task):
    """Only enforce a color when the user explicitly names exactly one."""
    names = {"红": "red", "紫": "purple", "蓝": "blue"}
    colors = {names[m.group(1)] for m in re.finditer(r"([红紫蓝])色气球", task)}
    colors.update(m.group(1).lower() for m in re.finditer(
        r"\b(red|purple|blue)\s+balloon\b", task, re.IGNORECASE))
    return next(iter(colors)) if len(colors) == 1 else None


def command_balloon_colors(commands):
    """Return every hit_balloon target found in the command block."""
    return re.findall(r"(?m)^\s*hit_balloon\s*:\s*([a-zA-Z]+)\s*$", commands or "")


def generate_validated_commands(model, tokenizer, base_msgs, task):
    expected = expected_balloon_color(task)
    for attempt in range(2):
        prompt = task if attempt == 0 else (
            task + "\n请重新生成完整命令。任务明确要求打击" + expected +
            "色气球，命令必须且只能包含 hit_balloon:" + expected + "。")
        commands = generate_commands(model, tokenizer, base_msgs, prompt)
        if expected is None:
            return commands
        targets = command_balloon_colors(commands)
        if targets == [expected]:
            return commands
        print(f"[颜色校验] 第{attempt + 1}次生成不匹配：任务={expected}, 命令={targets}；拒绝发布", flush=True)
    return None


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
