"""Generate and manually confirm one mission action at a time."""
import gc
import inspect
import json
import os
import re
import threading
import time
import uuid

from transformers import AutoModel, AutoTokenizer
import torch
import rospy
from std_msgs.msg import String

PROTOCOL_VERSION = 1
VALID_COMMANDS = ("takeoff", "cross_frame", "detect_aruco", "return_cross_frame", "land")
BALLOON_COLORS = ("red", "purple", "blue")
MAX_ATTEMPTS = max(1, int(os.environ.get("MISSION_MAX_ATTEMPTS", "3")))
RETRY_BUDGET_S = float(os.environ.get("MISSION_RETRY_BUDGET_S", "60"))
STATUS_TIMEOUT_S = float(os.environ.get("MISSION_STATUS_TIMEOUT_S", "180"))
ABORT_TIMEOUT_S = 5.0
MODEL_MAX_NEW_TOKENS = max(1, int(os.environ.get("MISSION_MAX_NEW_TOKENS", "256")))
MODEL_MAX_TIME_S = float(os.environ.get("MISSION_MODEL_MAX_TIME_S", "30"))
TERMINAL = ("SUCCESS", "FAILURE", "ABORTED", "TIMEOUT")
COLOR_NAMES = {"red": "红", "purple": "紫", "blue": "蓝"}


def load_model():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(script_dir, "prompts", "mission_prompt.txt"), encoding="utf-8") as prompt_file:
        knowledge_prompt = prompt_file.read()
    print("[1/3] 加载模型...", flush=True)
    model = AutoModel.from_pretrained(
        os.path.join(script_dir, "FM9G4B-V"), trust_remote_code=True,
        attn_implementation="sdpa", torch_dtype=torch.bfloat16
    ).eval().cuda()
    tokenizer = AutoTokenizer.from_pretrained(os.path.join(script_dir, "FM9G4B-V"), trust_remote_code=True)
    print("[2/3] 注入提示词...", flush=True)
    msgs = [{"role": "user", "content": [knowledge_prompt]}]
    reply = "".join(_bounded_chat(model, image=None, msgs=msgs, tokenizer=tokenizer, sampling=True, stream=True))
    msgs.append({"role": "assistant", "content": [reply]})
    print("[3/3] 模型就绪。", flush=True)
    return model, tokenizer, msgs


def _bounded_chat(model, **kwargs):
    """Apply only limits advertised by this model's chat signature."""
    try:
        parameters = inspect.signature(model.chat).parameters
    except (TypeError, ValueError):
        parameters = {}
    if "max_new_tokens" in parameters:
        kwargs["max_new_tokens"] = MODEL_MAX_NEW_TOKENS
    if "max_time" in parameters:
        kwargs["max_time"] = MODEL_MAX_TIME_S
    return model.chat(**kwargs)


def generate_commands(model, tokenizer, base_msgs, task_description):
    msgs = base_msgs.copy()
    msgs.append({"role": "user", "content": [task_description +
        "\n只输出本条指令明确要求的一个动作，使用唯一的 ```command 代码块；不要补充其他阶段。"]})
    content = ""
    for token in _bounded_chat(model, image=None, msgs=msgs, tokenizer=tokenizer, sampling=True, stream=True):
        print(token, flush=True, end="")
        content += token
    print(flush=True)
    gc.collect()
    torch.cuda.empty_cache()
    blocks = re.findall(r"```command\s*\n(.*?)```", content, re.DOTALL | re.IGNORECASE)
    return blocks[0].strip() if len(blocks) == 1 else None


def single_requested_command(task):
    text = re.sub(r"\s+", " ", task.lower().strip()).strip("，。,.!?！？;； ")
    text = re.sub(r"^(?:请执行|执行|请|please\s+)(?:\s*)", "", text)
    text = re.sub(r"(?:一下|操作|动作)$", "", text).strip()
    phrases = {
        "takeoff": ("起飞", "飞机起飞", "升空", "take off", "takeoff"),
        "cross_frame": ("穿越方框", "穿过方框", "穿过框", "穿框", "过框", "cross the frame", "fly through the frame", "cross frame"),
        "detect_aruco": ("识别二维码", "二维码识别", "识别aruco", "识别 aruco", "identify aruco", "detect aruco", "scan the qr code", "identify the qr code", "qr code"),
        "return_cross_frame": ("逆序穿越方框", "反向穿越方框", "逆序穿过框", "反向穿过框", "逆序穿过方框", "穿回来", "穿回方框", "再穿回框", "穿回框", "reverse through the frame", "return through the frame"),
        "land": ("返回起点并降落", "回到起点并降落", "返航降落", "返回起点降落", "降落", "land", "landing", "return home and land"),
    }
    for command, supported in phrases.items():
        if text in supported:
            return command
    match = re.fullmatch(r"(?:去)?(?:打破|打击|打|撞破|刺破|扎破|击破|击中)([红紫蓝])(?:颜色|色)?(?:的)?(?:气球|球)", text)
    if match:
        return "hit_balloon:" + {"红": "red", "紫": "purple", "蓝": "blue"}[match[1]]
    match = re.fullmatch(r"(?:hit|burst|pop) (?:the )?(red|purple|blue) balloon", text)
    return "hit_balloon:" + match[1] if match else None


def expected_balloon_color(task):
    command = single_requested_command(task)
    return command.split(":")[1] if command and command.startswith("hit_balloon:") else None


def command_balloon_colors(commands):
    return re.findall(r"(?m)^\s*hit_balloon\s*:\s*([a-zA-Z]+)\s*$", commands or "")


def command_for_single_request(commands):
    actual = [line.strip() for line in (commands or "").splitlines() if line.strip()]
    if len(actual) != 1:
        return None
    if actual[0] in VALID_COMMANDS:
        return actual[0]
    match = re.fullmatch(r"hit_balloon\s*:\s*(red|purple|blue)", actual[0])
    return "hit_balloon:" + match[1] if match else None


def requested_stage_problems(task):
    return [] if single_requested_command(task) else ["instruction is unsupported, ambiguous or names multiple stages"]


def requested_stage_count(task):
    return 1 if single_requested_command(task) else 2


def single_action_problems(commands, task):
    return command_problems(commands, None, task)


def command_problems(commands, expected, task=""):
    requested = single_requested_command(task)
    generated = command_for_single_request(commands)
    if requested is None:
        return ["operator instruction is unsupported or ambiguous"]
    if generated is None:
        return ["model must generate exactly one supported command"]
    if generated != requested:
        return [f"action mismatch: requested={requested}, generated={generated}"]
    if expected is not None and generated != "hit_balloon:" + expected:
        return ["color mismatch"]
    return []


def retry_prompt(task, expected):
    return task + ("\n请只生成用户明确要求的一个动作，放在 ```command 代码块中。"
                   "只可使用 takeoff、cross_frame、detect_aruco、return_cross_frame、"
                   "hit_balloon:red/purple/blue 或 land。不要补充其他阶段。")


def audit_event(event, **fields):
    print("[AUDIT] " + json.dumps(dict(event=event, monotonic_s=time.monotonic(), **fields),
                                 ensure_ascii=False), flush=True)


def generate_validated_commands(model, tokenizer, base_msgs, task):
    if requested_stage_problems(task):
        return None
    expected = expected_balloon_color(task)
    deadline = time.monotonic() + RETRY_BUDGET_S
    for attempt in range(MAX_ATTEMPTS):
        if attempt and time.monotonic() >= deadline:
            break
        audit_event("generation_start", attempt=attempt + 1, operator_input=task)
        try:
            commands = generate_commands(model, tokenizer, base_msgs, task if attempt == 0 else retry_prompt(task, expected))
        finally:
            audit_event("generation_end", attempt=attempt + 1)
        problems = command_problems(commands, expected, task)
        if not problems:
            return command_for_single_request(commands)
        print(f"[命令校验] 第{attempt + 1}次生成不合格：{'; '.join(problems)}", flush=True)
    return None


class MissionClient:
    def __init__(self):
        self.ready = None
        self.ready_received_at = 0.0
        self.ready_revision = 0
        self.results = {}
        self.requests = {}
        self.accepted = set()
        self.lock = threading.RLock()
        self.uncertain = False
        self.session_id = None
        self.epoch = None
        self.pending_request_id = None
        self.recovery_previous = None
        self.session_ready = False
        self.reset_confirmed = False
        self.controller_epoch_change = None
        self.request_pub = rospy.Publisher("/mission_request", String, queue_size=1)
        self.abort_pub = rospy.Publisher("/mission_abort", String, queue_size=1)
        rospy.Subscriber("/mission_ready", String, self._on_ready, queue_size=1)
        rospy.Subscriber("/mission_status", String, self._on_status, queue_size=20)

    def _decode(self, raw):
        try:
            value = json.loads(raw.data)
            if (isinstance(value, dict) and value.get("protocol") == PROTOCOL_VERSION
                    and isinstance(value.get("server_epoch"), str) and value["server_epoch"]):
                return value
        except (ValueError, TypeError, AttributeError):
            pass
        return None

    def _belongs_to_round(self, value):
        return bool(self.epoch and self.session_id and value.get("server_epoch") == self.epoch
                    and value.get("session_id") == self.session_id)

    def _on_ready(self, raw):
        value = self._decode(raw)
        if not value or value.get("status") != "READY":
            return
        with self.lock:
            if self.session_id and value.get("server_epoch") != self.epoch:
                self.controller_epoch_change = {
                    "old_epoch": self.epoch,
                    "new_epoch": value["server_epoch"],
                    "pending_request_id": self.pending_request_id,
                    "message": "Controller restarted; original request identity is retained. Reconcile or abort externally before any movement.",
                }
                self.uncertain = True
                self.session_ready = False
                self.ready = value
                self.ready_received_at = time.monotonic()
                return
            if self.session_id and not self._belongs_to_round(value):
                return
            self.ready = value
            self.ready_received_at = time.monotonic()
            self.ready_revision += 1
            if self._belongs_to_round(value):
                self.session_ready = True
                request_id = value.get("active_request_id")
                if request_id in self.requests and value.get("active_command") == self.requests[request_id]:
                    self.accepted.add(request_id)

    def _on_status(self, raw):
        value = self._decode(raw)
        if not value:
            return
        audit_event("status_received", source="/mission_status", payload=value)
        with self.lock:
            request_id = value.get("request_id")
            if not self._belongs_to_round(value) or request_id not in self.requests:
                return
            if value.get("command") != self.requests[request_id]:
                return
            if value.get("status") == "ACCEPTED":
                self.accepted.add(request_id)
            if value.get("status") in ("ACCEPTED", "REJECTED") + TERMINAL:
                self.results.setdefault(request_id, []).append(value)
                print("[STATUS] " + json.dumps(value, ensure_ascii=False), flush=True)

    def _wait_for(self, predicate, timeout):
        deadline = time.monotonic() + timeout
        while not rospy.is_shutdown() and time.monotonic() < deadline:
            result = predicate()
            if result is not None:
                return result
            time.sleep(0.05)
        return None

    def _pop_result(self, request_id):
        with self.lock:
            queued = self.results.get(request_id)
            return queued.pop(0) if queued else None

    def _current_ready(self):
        with self.lock:
            return self.ready if self.ready and time.monotonic() - self.ready_received_at <= 2.5 else None

    def reconcile_last_terminal(self, request_id):
        with self.lock:
            ready = self._current_ready()
            if (not ready or not self._belongs_to_round(ready) or request_id not in self.requests
                    or ready.get("last_request_id") != request_id
                    or ready.get("last_command") != self.requests[request_id]
                    or ready.get("last_status") not in TERMINAL):
                return None
            return {"request_id": request_id, "status": ready["last_status"],
                    "reason": ready.get("last_reason", ""), "accepted": True}

    def _publish_request(self, request_id, command=None, reset=False):
        payload = {"protocol": PROTOCOL_VERSION, "server_epoch": self.epoch,
                   "session_id": self.session_id, "request_id": request_id}
        with self.lock:
            self.requests[request_id] = "" if reset else command
        payload.update({"reset": True} if reset else {"command": command})
        print("[SEND] " + json.dumps(payload, ensure_ascii=False), flush=True)
        self.request_pub.publish(String(data=json.dumps(payload)))

    def publish_abort(self, request_id):
        if not (self.epoch and self.session_id and request_id in self.requests):
            return False
        payload = {"protocol": PROTOCOL_VERSION, "server_epoch": self.epoch,
                   "session_id": self.session_id, "request_id": request_id}
        print("[ABORT] " + json.dumps(payload, ensure_ascii=False), flush=True)
        self.abort_pub.publish(String(data=json.dumps(payload)))
        return True

    def _finish(self, request_id, result):
        print("[RESULT] " + json.dumps({"server_epoch": self.epoch, "session_id": self.session_id,
              "request_id": request_id, "command": self.requests[request_id],
              "status": result["status"], "reason": result.get("reason", "")}, ensure_ascii=False), flush=True)
        with self.lock:
            if self.pending_request_id == request_id:
                previous = self.recovery_previous
                self.recovery_previous = None
                if previous and result["status"] != "SUCCESS":
                    self.pending_request_id, self.uncertain = previous
                else:
                    self.pending_request_id = None
                    self.uncertain = bool(self.controller_epoch_change)
        return result["status"], result.get("reason", "")

    def _poll_pending(self):
        request_id = self.pending_request_id
        if not request_id:
            return None
        while True:
            result = self._pop_result(request_id)
            if result is None:
                break
            status = result["status"]
            if status == "REJECTED":
                if request_id not in self.accepted:
                    return self._finish(request_id, result)
            elif status in TERMINAL:
                return self._finish(request_id, result)
        result = self.reconcile_last_terminal(request_id)
        return self._finish(request_id, result) if result else None

    def reconcile_pending(self):
        return self._poll_pending()

    def abort_pending(self):
        request_id = self.pending_request_id
        if not request_id:
            return None
        self.uncertain = True
        self.publish_abort(request_id)
        return self._wait_for(self._poll_pending, ABORT_TIMEOUT_S)

    def initialize(self):
        if self.controller_epoch_change or self.pending_request_id or self.uncertain:
            raise RuntimeError(self._recovery_lock_message())
        self.reset_confirmed = False
        self.session_ready = False
        ready = self._wait_for(self._current_ready, 10.0)
        if ready is None or ready.get("state") != "IDLE":
            raise RuntimeError("No fresh IDLE executor heartbeat; reset disabled")
        self.epoch = ready["server_epoch"]
        self.session_id = uuid.uuid4().hex
        with self.lock:
            self.ready = None
            self.ready_received_at = 0.0
        request_id = uuid.uuid4().hex
        self._publish_request(request_id, reset=True)
        response = self._wait_for(lambda: self._pop_result(request_id), 10.0)
        if not response or response.get("status") != "SUCCESS" or response.get("reason") != "RESET":
            raise RuntimeError("Round reset was not confirmed; movement disabled")
        ready = self._wait_for(lambda: self._current_ready() if self.session_ready else None, 5.0)
        if not ready or not self._belongs_to_round(ready) or ready.get("state") != "IDLE":
            self.session_ready = False
            raise RuntimeError("No fresh matching READY for the reset session; movement disabled")
        self.reset_confirmed = True

    def _recovery_lock_message(self):
        if self.controller_epoch_change:
            return ("Controller epoch changed; original request identity is retained. "
                    "Do not reset or move. Reconcile/abort the original request with the external controller, "
                    "then start a fresh session only after a human confirms the aircraft state.")
        return ("Prior request outcome is unresolved; use reconcile or abort. No ordinary resend is performed. "
                "If no matching terminal arrives, use external controller recovery to stop/land safely; "
                "do not reset or replace the original session/request identity.")

    def _settle_before_emergency(self):
        if self.controller_epoch_change:
            return False
        if not (self.pending_request_id or self.uncertain):
            return True
        request_id = self.pending_request_id
        readiness_before = self.ready_revision
        result = self.reconcile_pending()
        if self.pending_request_id:
            result = self.abort_pending()
            if result and result[0] in TERMINAL:
                ready = self._wait_for(
                    lambda: self._current_ready() if self.ready_revision > readiness_before else None,
                    ABORT_TIMEOUT_S)
                if ready is None:
                    raise RuntimeError("Original request settled; await a fresh nonbusy READY before emergency_land")
        if request_id and (not result or result[0] not in TERMINAL):
            self.pending_request_id = request_id
            self.uncertain = True
            return False
        if self.pending_request_id or self.uncertain:
            return False
        return True

    def execute(self, command):
        if command not in VALID_COMMANDS + ("emergency_land",) and not re.fullmatch(r"hit_balloon:(red|purple|blue)", command):
            raise RuntimeError("Unsupported command")
        emergency = command == "emergency_land"
        if emergency and not self._settle_before_emergency():
            raise RuntimeError("Emergency land blocked: " + self._recovery_lock_message())
        if self.controller_epoch_change:
            raise RuntimeError(self._recovery_lock_message())
        if (self.pending_request_id or self.uncertain) and not emergency:
            raise RuntimeError(self._recovery_lock_message())
        ready = self._current_ready()
        allowed_states = ("IDLE", "RECOVERY_REQUIRED") if emergency else ("IDLE",)
        busy = ready and (ready.get("busy") or ready.get("status") == "BUSY" or ready.get("active_request_id"))
        if (not self.reset_confirmed or not self.session_ready or not ready or not self._belongs_to_round(ready)
                or ready.get("state") not in allowed_states or busy
                or (not emergency and ready.get("recovery_required", False))):
            raise RuntimeError("Executor readiness does not allow this action in the current session")
        request_id = uuid.uuid4().hex
        if emergency:
            self.recovery_previous = (self.pending_request_id, self.uncertain)
        self.pending_request_id = request_id
        try:
            self._publish_request(request_id, command=command)
            result = self._wait_for(self._poll_pending, STATUS_TIMEOUT_S)
            if result is not None:
                return result
        except KeyboardInterrupt:
            self.uncertain = True
            try:
                result = self.abort_pending()
            except KeyboardInterrupt:
                result = None
            raise RuntimeError("Interrupted; correlated abort requested. Recovery result: " + repr(result)) from None
        except Exception:
            self.uncertain = True
            raise
        self.uncertain = True
        raise RuntimeError("Request outcome uncertain; no automatic resend. Use reconcile, abort or emergency_land")


def main():
    rospy.init_node("mission_once", anonymous=True)
    client = MissionClient()
    rospy.sleep(0.5)
    print("[模型预算] 重试预算只限制两次调用之间；模型声明支持时传入 token/time 上限，不能保证 CUDA 硬超时。"
          "推理卡住时 Ctrl+C 返回恢复界面；无法中断时请使用独立的外部控制器安全停止/降落，勿重启控制器伪造新会话。", flush=True)
    model, tokenizer, base_msgs = load_model()
    try:
        client.initialize()
    except RuntimeError as exc:
        print(f"[执行器未就绪] {exc}", flush=True)
        return
    while not rospy.is_shutdown():
        try:
            task = input("\n输入单阶段指令；恢复：reconcile / abort / emergency_land；q 退出：").strip()
        except KeyboardInterrupt:
            print("\n恢复结果：", client.abort_pending(), flush=True)
            continue
        except EOFError:
            print("\n恢复结果：", client.abort_pending(), flush=True)
            while client.pending_request_id and not rospy.is_shutdown():
                print("[输入已关闭] 保留当前请求，等待匹配终态；不会重发飞行动作。", flush=True)
                try:
                    result = client._wait_for(client.reconcile_pending, ABORT_TIMEOUT_S)
                    if result is not None:
                        print("[原请求恢复结果]", result, flush=True)
                except KeyboardInterrupt:
                    print("[恢复接口保留]", client.abort_pending(), flush=True)
            return
        audit_event("operator_input", operator_input=task)
        if task.lower() in ("q", "quit", "exit"):
            if client.pending_request_id:
                print("恢复结果：", client.abort_pending(), flush=True)
                if client.pending_request_id:
                    print("[退出被阻止] 原请求尚无终态；请继续 reconcile / abort / emergency_land。", flush=True)
                    continue
            return
        if task.lower() in ("reconcile", "abort"):
            result = client.reconcile_pending() if task.lower() == "reconcile" else client.abort_pending()
            print("[原请求恢复结果]", result or "尚无匹配终态；保持锁定。", flush=True)
            continue
        emergency = task.lower() == "emergency_land"
        if not emergency and (client.uncertain or client.pending_request_id):
            print("[锁定] 请先 reconcile / abort，或明确选择 emergency_land。", flush=True)
            continue
        if emergency:
            command = "emergency_land"
            print("紧急原地降落：直接 Land，不返航。", flush=True)
        else:
            if requested_stage_problems(task):
                print("[拒绝执行] 请使用明确、受支持的单阶段指令。", flush=True)
                continue
            try:
                command = generate_validated_commands(model, tokenizer, base_msgs, task)
            except KeyboardInterrupt:
                print("\n[模型推理已中断] 未发送命令；可使用 reconcile / abort / emergency_land。", flush=True)
                continue
            except RuntimeError as exc:
                print(f"[模型推理失败] {exc}", flush=True)
                continue
            if command is None:
                print("[拒绝执行] 模型未生成匹配的唯一动作。", flush=True)
                continue
        print(f"\n将要请求的唯一动作：{command}", flush=True)
        try:
            answer = input("确认后输入 RUN；其他输入取消：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n未发送命令。", flush=True)
            continue
        if answer != "RUN":
            continue
        audit_event("run_confirmed", operator_input=task, command=command)
        try:
            status, reason = client.execute(command)
            print(f"[本请求结果] {command}: {status}; {reason}", flush=True)
        except RuntimeError as exc:
            print(f"[恢复接口保留] {exc}", flush=True)


if __name__ == "__main__":
    main()
