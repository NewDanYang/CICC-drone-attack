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
import json
import threading
from transformers import AutoModel, AutoTokenizer
try:
    from transformers import AutoProcessor
except ImportError:  # The offline command-only test stubs do not provide it.
    AutoProcessor = None
import torch
import rospy
from std_msgs.msg import String


MULTIMODAL_PROMPT = (
    "请识别完整图像中实际可见的目标，只输出一个 JSON 对象，不要解释或 Markdown。"
    "顶层只能有 objects 数组；每个对象只能有 category、color、bbox 四个字段。"
    "category 只能是 balloon、frame、obstacle、landing_marker、smoke 或 unknown；"
    "气球的 color 只能是 red、purple、blue、unknown，其他目标填 unknown。"
    "bbox 是像素坐标 [x1,y1,x2,y2]，原点在左上，范围是 640x480；"
    "只列出图中可见目标，不要猜测完全遮挡的目标。"
)
MULTIMODAL_COLORS = {"red", "purple", "blue", "unknown"}
MULTIMODAL_CATEGORIES = {
    "balloon", "frame", "obstacle", "landing_marker", "smoke", "unknown"
}


def parse_multimodal_answer(answer):
    """Validate one strict image answer and return normalized objects.

    This parser deliberately has no fallback to YOLO, HSV, or a guessed box.
    A malformed or stale model answer therefore becomes an invalid frame.
    """
    if isinstance(answer, (tuple, list)):
        answer = answer[0] if answer else ""
    text = answer if isinstance(answer, str) else str(answer)
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) < 3 or lines[-1].strip() != "```":
            raise ValueError("unterminated JSON fence")
        text = "\n".join(lines[1:-1]).strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        # The model may concatenate two top-level arrays with a comma. Wrap
        # that one specific form into an outer array before schema checking.
        if text.startswith("[") and text.count("[", 0, len(text)) >= 2:
            obj = json.loads("[" + text + "]")
        else:
            raise
    if isinstance(obj, dict) and set(obj) == {"objects"} and isinstance(obj["objects"], list):
        rows = obj["objects"]
    elif isinstance(obj, list):
        # FM9G4B-V sometimes emits one JSON array per visual group even when
        # asked for one object. Accept only arrays of the same object records;
        # this is schema normalization, never a detector fallback.
        rows = []
        for group in obj:
            if isinstance(group, list):
                rows.extend(group)
            elif isinstance(group, dict):
                rows.append(group)
            else:
                raise ValueError("nested list contains a non-object record")
    else:
        raise ValueError("top-level schema must be {objects: []} or object arrays")
    normalized = []
    for item in rows:
        if not isinstance(item, dict) or set(item) != {"category", "color", "bbox"}:
            raise ValueError("object schema mismatch")
        category, color, box = item["category"], item["color"], item["bbox"]
        if category not in MULTIMODAL_CATEGORIES or color not in MULTIMODAL_COLORS:
            raise ValueError("unknown category or color")
        if not isinstance(box, list) or len(box) != 4:
            raise ValueError("bbox must contain four coordinates")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in box):
            raise ValueError("bbox coordinates must be numeric")
        x1, y1, x2, y2 = [int(round(v)) for v in box]
        # Keep a model box that straddles the image edge usable, while
        # dropping a record that is entirely outside the image.
        x1, x2 = max(0, min(640, x1)), max(0, min(640, x2))
        y1, y2 = max(0, min(480, y1)), max(0, min(480, y2))
        if x1 >= x2 or y1 >= y2:
            continue
        normalized.append({"category": category, "color": color,
                           "bbox": [x1, y1, x2, y2]})
    return normalized


class MultimodalBalloonBridge:
    """One-model image inference plus a non-semantic bbox tracker.

    The class is intentionally created by this same mission_once process. It
    publishes only frames whose last semantic decision came from FM9G4B-V;
    optical flow merely transports that decision between model calls.
    """

    def __init__(self, model, tokenizer, processor):
        from sensor_msgs.msg import Image
        from common_msgs.msg import Objects, Obj, DetEnable

        self._Image = Image
        self._Objects, self._Obj, self._DetEnable = Objects, Obj, DetEnable
        self.model, self.tokenizer, self.processor = model, tokenizer, processor
        self.image_topic = os.environ.get("MULTIMODAL_IMAGE_TOPIC", "/rflysim/sensor2/img_rgb")
        self.objects_topic = os.environ.get("MULTIMODAL_OBJECTS_TOPIC", "/multimodal/objects")
        self.period_s = float(os.environ.get("MULTIMODAL_PERIOD_S", "2.5"))
        self.max_hold_s = float(os.environ.get("MULTIMODAL_MAX_HOLD_S", "3.5"))
        self.debug_display = os.environ.get("MULTIMODAL_DEBUG_DISPLAY", "1") not in ("0", "false", "False")
        self.lock = threading.RLock()
        self.latest_msg = None
        self.latest_seq = -1
        self.active_color = None
        self.last_model_box = None
        self.track_box = None
        self.last_model_time = 0.0
        self.prev_gray = None
        self.track_points = None
        self.last_control_log = 0.0
        self.window_ready = False
        self.cv2 = None
        self.np = None
        try:
            import cv2
            import numpy as np
            self.cv2, self.np = cv2, np
        except Exception as exc:
            rospy.logerr("MULTIMODAL_NO_OPENCV %s", exc)
        self.objects_pub = rospy.Publisher(self.objects_topic, Objects, queue_size=10)
        self.debug_pub = rospy.Publisher("/multimodal/debug_image", Image, queue_size=2)
        self.gate_pub = rospy.Publisher("/detect_ctrl", DetEnable, queue_size=2, latch=True)
        rospy.Subscriber(self.image_topic, Image, self._image_callback, queue_size=1)
        rospy.Subscriber("/multimodal/balloon_target", String, self._gate_callback, queue_size=2)
        rospy.Subscriber("/mission_result", String, self._result_callback, queue_size=2)
        self.worker = threading.Thread(target=self._inference_loop, name="multimodal-inference", daemon=True)
        self.worker.start()
        rospy.loginfo("MULTIMODAL_BRIDGE_READY image=%s objects=%s period=%.2fs max_hold=%.2fs",
                      self.image_topic, self.objects_topic, self.period_s, self.max_hold_s)

    def _gate_callback(self, msg):
        value = msg.data.strip()
        with self.lock:
            if value.startswith("start:"):
                color = value.split(":", 1)[1].strip().lower()
                if color not in ("red", "purple", "blue"):
                    rospy.logwarn("MULTIMODAL_GATE_REJECT color=%s", color)
                    return
                self.active_color = color
                self.last_model_box = self.track_box = None
                self.last_model_time = 0.0
                self.prev_gray = self.track_points = None
                self.latest_seq = -1
                gate = self._DetEnable(); gate.is_open = False
                self.gate_pub.publish(gate)
                rospy.loginfo("MULTIMODAL_GATE_START color=%s yolo_objects=disabled", color)
            elif value == "stop":
                self.active_color = None
                self.last_model_box = self.track_box = None
                gate = self._DetEnable(); gate.is_open = True
                self.gate_pub.publish(gate)
                rospy.loginfo("MULTIMODAL_GATE_STOP yolo_objects=enabled")

    def _result_callback(self, _msg):
        # bt_ros publishes a result after success, failure, or abort. Do not
        # leave the YOLO node disabled between missions.
        self._gate_callback(String(data="stop"))

    def _image_callback(self, msg):
        with self.lock:
            self.latest_msg = msg
            self.latest_seq += 1
            active = self.active_color is not None
        if active and self.cv2 is not None:
            self._track_and_publish(msg)

    def _to_rgb(self, msg):
        if self.np is None:
            raise RuntimeError("numpy unavailable")
        channels = 4 if msg.encoding in ("rgba8", "bgra8") else 3
        arr = self.np.frombuffer(msg.data, dtype=self.np.uint8)
        arr = arr.reshape((msg.height, msg.step // channels, channels))[:, :msg.width, :]
        if msg.encoding in ("bgr8", "bgra8"):
            arr = arr[:, :, ::-1]
        return arr[:, :, :3].copy()

    def _track_and_publish(self, msg):
        now = time.monotonic()
        try:
            rgb = self._to_rgb(msg)
            gray = self.cv2.cvtColor(rgb, self.cv2.COLOR_RGB2GRAY)
        except Exception as exc:
            rospy.logwarn_throttle(5.0, "MULTIMODAL_IMAGE_ERROR %s", exc)
            return
        with self.lock:
            if self.active_color is None:
                return
            box = self.track_box
            age = now - self.last_model_time if self.last_model_time else float("inf")
            old_gray, points = self.prev_gray, self.track_points
        if box is not None and old_gray is not None and points is not None:
            try:
                nxt, status, _ = self.cv2.calcOpticalFlowPyrLK(
                    old_gray, gray, points, None, winSize=(21, 21), maxLevel=2)
                good_new = nxt[status.reshape(-1) == 1]
                good_old = points[status.reshape(-1) == 1]
                if len(good_new) >= 2:
                    delta = self.np.median(good_new - good_old, axis=0)
                    x1, y1, x2, y2 = box
                    dx, dy = float(delta[0]), float(delta[1])
                    box = [int(round(max(0, min(640, x1 + dx)))),
                           int(round(max(0, min(480, y1 + dy)))),
                           int(round(max(0, min(640, x2 + dx)))),
                           int(round(max(0, min(480, y2 + dy))))]
                    if box[2] <= box[0] or box[3] <= box[1]:
                        box = None
                    with self.lock:
                        self.track_box = box
                        self.prev_gray, self.track_points = gray, good_new.reshape(-1, 1, 2)
            except Exception:
                pass
        if box is not None and age <= self.max_hold_s:
            self._publish_box(box, msg.header, source="tracker")
            if now - self.last_control_log >= 1.0:
                rospy.loginfo("MULTIMODAL_CONTROL color=%s bbox=%s source=tracker age=%.2f topic=%s",
                              self.active_color, box, age, self.objects_topic)
                self.last_control_log = now
        self._publish_debug(rgb, box, age, msg.header)

    def _publish_box(self, box, header, source):
        with self.lock:
            color = self.active_color
        if color is None:
            return
        out = self._Objects(); out.header = header; out.source_id = 9
        item = self._Obj(); item.class_name = color + "_balloon"
        item.left_top_x, item.left_top_y, item.right_bottom_x, item.right_bottom_y = box
        item.center_x = int(round((box[0] + box[2]) / 2.0))
        item.center_y = int(round((box[1] + box[3]) / 2.0))
        item.score = 1.0
        out.objects = [item]
        self.objects_pub.publish(out)

    def _publish_debug(self, rgb, box, age, header):
        if self.cv2 is None:
            return
        canvas = rgb[:, :, ::-1].copy()
        with self.lock:
            model_box, color = self.last_model_box, self.active_color
        if model_box:
            self.cv2.rectangle(canvas, (model_box[0], model_box[1]), (model_box[2], model_box[3]), (255, 0, 255), 2)
        if box:
            self.cv2.rectangle(canvas, (box[0], box[1]), (box[2], box[3]), (0, 255, 0), 2)
        label = "九格 color=%s age=%.1fs" % (color or "-", age if age != float("inf") else -1)
        self.cv2.putText(canvas, label, (8, 24), self.cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        msg = self._Image(); msg.header = header; msg.height, msg.width = canvas.shape[:2]
        msg.encoding, msg.step, msg.data = "bgr8", int(canvas.shape[1] * 3), canvas.tobytes()
        self.debug_pub.publish(msg)
        if self.debug_display:
            try:
                self.cv2.imshow("九格多模态感知", canvas)
                self.cv2.waitKey(1)
                if not self.window_ready:
                    self.window_ready = True
                    rospy.loginfo("MULTIMODAL_WINDOW_READY title=九格多模态感知")
            except Exception as exc:
                self.debug_display = False
                rospy.logwarn("MULTIMODAL_WINDOW_UNAVAILABLE %s; debug topic remains active", exc)

    def _inference_loop(self):
        last_seq, last_call = -1, 0.0
        while not rospy.is_shutdown():
            with self.lock:
                active, msg, seq = self.active_color, self.latest_msg, self.latest_seq
            now = time.monotonic()
            if not active or msg is None or seq == last_seq or now - last_call < self.period_s:
                time.sleep(0.02)
                continue
            last_seq, last_call = seq, now
            try:
                from PIL import Image as PILImage
                rgb = self._to_rgb(msg)
                image = PILImage.fromarray(rgb, mode="RGB")
                kwargs = dict(image=image, msgs=[{"role": "user", "content": [MULTIMODAL_PROMPT]}],
                              tokenizer=self.tokenizer, sampling=False, stream=False,
                              num_beams=1, max_new_tokens=256)
                if self.processor is not None:
                    kwargs["processor"] = self.processor
                started = time.perf_counter()
                with torch.inference_mode():
                    answer = self.model.chat(**kwargs)
                latency = time.perf_counter() - started
                objects = parse_multimodal_answer(answer)
                with self.lock:
                    color = self.active_color
                candidates = [o for o in objects if o["category"] == "balloon" and o["color"] == color]
                if not candidates:
                    raise ValueError("no visible requested-color balloon")
                box = max(candidates, key=lambda o: (o["bbox"][2] - o["bbox"][0]) * (o["bbox"][3] - o["bbox"][1]))["bbox"]
                gray = self.cv2.cvtColor(rgb, self.cv2.COLOR_RGB2GRAY) if self.cv2 is not None else None
                points = None
                if gray is not None:
                    x1, y1, x2, y2 = box
                    points = self.np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], dtype=self.np.float32).reshape(-1, 1, 2)
                with self.lock:
                    self.last_model_box, self.track_box = box, box
                    self.last_model_time, self.prev_gray, self.track_points = time.monotonic(), gray, points
                self._publish_box(box, msg.header, source="model")
                rospy.loginfo("MULTIMODAL_DECISION model_frame=%s color=%s bbox=%s objects=%d latency=%.3fs publish=%s",
                              seq, color, box, len(objects), latency, self.objects_topic)
            except Exception as exc:
                raw_answer = locals().get("answer", "")
                if isinstance(raw_answer, (tuple, list)):
                    raw_answer = raw_answer[0] if raw_answer else ""
                rospy.logwarn("MULTIMODAL_INFERENCE_INVALID frame=%s error=%s raw=%r",
                              seq, exc, str(raw_answer)[:1000])


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
    processor = None
    if AutoProcessor is not None:
        try:
            processor = AutoProcessor.from_pretrained(model_dir, trust_remote_code=True)
        except Exception as exc:
            print(f"[多模态] 图像处理器加载失败，将使用模型默认处理：{exc}", flush=True)
    # Keep the historical three-value return contract used by offline probes;
    # the bridge reuses this processor without loading a second model.
    model._tcei_processor = processor

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
    multimodal_bridge = MultimodalBalloonBridge(
        model, tokenizer, getattr(model, "_tcei_processor", None)
    )

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
                # Formal trials invoke mission_once with argv and stdin=/dev/null.
                # Keep this same model process alive so the multimodal bridge can
                # receive the balloon-stage gate and publish image decisions
                # while bt_ros executes the command sequence.
                rospy.spin()
                return
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
