"""Offline protocol tests; no ROS runtime, model loading or physical commands."""
import importlib.util
import json
import pathlib
import sys
import threading
import types
import unittest
from unittest.mock import patch

TARGET = pathlib.Path(__file__).resolve().parents[1] / "deploy" / "mission_once.py"
stubs = {name: types.ModuleType(name) for name in ("transformers", "torch", "rospy", "std_msgs", "std_msgs.msg")}
stubs["transformers"].AutoModel = stubs["transformers"].AutoTokenizer = object
stubs["std_msgs.msg"].String = type("String", (), {"__init__": lambda self, data="": setattr(self, "data", data)})
with patch.dict(sys.modules, stubs):
    spec = importlib.util.spec_from_file_location("mission_once_test", TARGET)
    mo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mo)


def message(payload):
    return types.SimpleNamespace(data=json.dumps(payload))


class Publisher:
    def __init__(self, callback):
        self.callback = callback
        self.messages = []

    def publish(self, msg):
        payload = json.loads(msg.data)
        self.messages.append(payload)
        self.callback(payload)


class Ros:
    def __init__(self):
        self.callbacks = {}
        self.publishers = {}
        self.on_command = lambda req: self.status(req, "SUCCESS")
        self.on_abort = lambda req: self.status(req, "ABORTED")
        self.reset_ready = True

    def Publisher(self, topic, *_args, **_kwargs):
        pub = Publisher(self.request if topic == "/mission_request" else self.abort)
        self.publishers[topic] = pub
        return pub

    def Subscriber(self, topic, _type, callback, **_kwargs):
        self.callbacks[topic] = callback

    def is_shutdown(self):
        return False

    def ready(self, session="", server_epoch="epoch-a", **extra):
        payload = dict(protocol=1, server_epoch=server_epoch, session_id=session,
                       status="READY", state="IDLE")
        payload.update(extra)
        self.callbacks["/mission_ready"](message(payload))

    def status(self, request, status, **extra):
        payload = dict(request, status=status, reason="")
        payload.pop("reset", None)
        payload.setdefault("command", "")
        payload.update(extra)
        self.callbacks["/mission_status"](message(payload))

    def request(self, req):
        if req.get("reset"):
            self.status(req, "SUCCESS", reason="RESET")
            if self.reset_ready:
                self.ready(req["session_id"])
        else:
            self.on_command(req)

    def abort(self, req):
        active = self.publishers["/mission_request"].messages[-1]
        self.on_abort(dict(req, command=active.get("command", "")))


class ParserTests(unittest.TestCase):
    def test_document_stage_wording(self):
        for task, expected in (
            ("飞机起飞", "takeoff"), ("穿框", "cross_frame"),
            ("穿过框", "cross_frame"), ("识别二维码", "detect_aruco"),
            ("再穿回框", "return_cross_frame"),
            ("去打击红色气球", "hit_balloon:red"),
            ("打击蓝色气球", "hit_balloon:blue"),
            ("刺破紫球", "hit_balloon:purple"),
            ("回到起点并降落", "land"),
        ):
            with self.subTest(task=task):
                self.assertEqual(mo.single_requested_command(task), expected)
        for task in ("不要刺破紫球", "飞机起飞，穿框", "打击红色气球并降落",
                     "打击红色和蓝色气球", "飞机起飞，然后穿过框，再去识别二维码"):
            with self.subTest(task=task):
                self.assertIsNone(mo.single_requested_command(task))
        with patch.object(mo, "generate_commands", return_value="hit_balloon:red"):
            self.assertIsNone(mo.generate_validated_commands(None, None, [], "刺破紫球"))

    def test_supported_single_phrases(self):
        for task, command in (("请起飞。", "takeoff"), ("穿过方框", "cross_frame"),
                              ("识别二维码", "detect_aruco"), ("逆序穿越方框", "return_cross_frame"),
                              ("撞破蓝色球", "hit_balloon:blue"), ("返回起点并降落", "land"),
                              ("please take off", "takeoff"), ("reverse through the frame", "return_cross_frame"),
                              ("pop the purple balloon", "hit_balloon:purple"), ("land", "land"),
                              ("去打蓝色气球", "hit_balloon:blue"), ("撞破红颜色的气球", "hit_balloon:red")):
            with self.subTest(task=task):
                self.assertEqual(mo.single_requested_command(task), command)

    def test_ambiguous_compound_negative_unsupported(self):
        for task in ("逆序穿越方框并降落", "reverse through the frame then land", "不要起飞", "do not land",
                     "don't take off", "不打红色气球，打蓝色气球", "hit red and blue balloon", "打红蓝气球",
                     "起飞再降落", "land unless safe", "emergency_land", "任意飞到某地"):
            with self.subTest(task=task):
                self.assertIsNone(mo.single_requested_command(task))

    def test_model_source_canonical_and_no_fallback(self):
        with patch.object(mo, "generate_commands", side_effect=["hit_balloon:purple", " hit_balloon : blue "]) as generate:
            self.assertEqual(mo.generate_validated_commands(None, None, [], "撞破蓝色气球"), "hit_balloon:blue")
            self.assertEqual(generate.call_count, 2)
        with patch.object(mo, "generate_commands", return_value="takeoff\nland") as generate:
            self.assertIsNone(mo.generate_validated_commands(None, None, [], "起飞"))
            self.assertEqual(generate.call_count, mo.MAX_ATTEMPTS)
        with patch.object(mo, "generate_commands") as generate:
            self.assertIsNone(mo.generate_validated_commands(None, None, [], "不要起飞"))
            generate.assert_not_called()

    def test_stream_output_requires_one_command_fence(self):
        from unittest.mock import Mock
        model = Mock()
        cuda = types.SimpleNamespace(empty_cache=lambda: None)
        for output, expected in (("```command\ntakeoff\n```", "takeoff"),
                                 ("```command\ntakeoff\n```\n```command\nland\n```", None),
                                 ("```python\ntakeoff\n```", None), ("takeoff", None)):
            with self.subTest(output=output), patch.object(mo.torch, "cuda", cuda, create=True), \
                    patch("builtins.print"):
                model.chat.return_value = iter(output)
                self.assertEqual(mo.generate_commands(model, None, [], "起飞"), expected)

    def test_model_limits_only_use_explicitly_supported_parameters(self):
        class BoundedModel:
            def chat(self, max_new_tokens=None, max_time=None, **kwargs):
                return max_new_tokens, max_time
        self.assertEqual(mo._bounded_chat(BoundedModel()),
                         (mo.MODEL_MAX_NEW_TOKENS, mo.MODEL_MAX_TIME_S))
        class LegacyModel:
            def chat(self, image=None):
                return image
        self.assertIsNone(mo._bounded_chat(LegacyModel(), image=None))

    def test_wrong_action_and_emergency_not_model_commands(self):
        self.assertTrue(mo.command_problems("land", None, "起飞"))
        self.assertIsNone(mo.command_for_single_request("emergency_land"))


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.ros = Ros()
        self.patch = patch.object(mo, "rospy", self.ros)
        self.patch.start()
        self.timeout = patch.object(mo, "STATUS_TIMEOUT_S", 0.2)
        self.timeout.start()
        self.console = patch("builtins.print")
        self.console.start()
        self.client = mo.MissionClient()
        self.ros.ready()
        self.client.initialize()

    def tearDown(self):
        self.console.stop()
        self.timeout.stop()
        self.patch.stop()

    def test_only_request_and_abort_publishers(self):
        self.assertEqual(set(self.ros.publishers), {"/mission_request", "/mission_abort"})

    def test_synchronous_accept_then_terminal_fifo(self):
        def command(req):
            self.ros.status(req, "ACCEPTED")
            self.ros.status(req, "SUCCESS")
        self.ros.on_command = command
        self.assertEqual(self.client.execute("takeoff"), ("SUCCESS", ""))
        self.assertIsNone(self.client.pending_request_id)

    def test_async_accept_rejected_duplicate_then_terminal(self):
        threads = []
        def command(req):
            self.ros.status(req, "ACCEPTED")
            self.ros.status(req, "REJECTED", reason="BUSY")
            thread = threading.Timer(0.01, lambda: self.ros.status(req, "SUCCESS"))
            threads.append(thread)
            thread.start()
        self.ros.on_command = command
        self.assertEqual(self.client.execute("takeoff"), ("SUCCESS", ""))
        for thread in threads:
            thread.join()

    def test_lost_acceptance_correlated_terminal_is_authoritative(self):
        self.assertEqual(self.client.execute("takeoff"), ("SUCCESS", ""))

    def test_lost_terminal_reconciles_ready_in_execute(self):
        threads = []
        def command(req):
            self.ros.status(req, "ACCEPTED")
            def terminal_summary():
                self.ros.ready(req["session_id"], last_request_id=req["request_id"], last_command=req["command"],
                               last_status="SUCCESS", last_reason="summary")
            thread = threading.Timer(0.01, terminal_summary)
            threads.append(thread)
            thread.start()
        self.ros.on_command = command
        self.assertEqual(self.client.execute("takeoff"), ("SUCCESS", "summary"))
        for thread in threads:
            thread.join()

    def test_genuine_rejection_clears_pending_allows_next(self):
        self.ros.on_command = lambda req: self.ros.status(req, "REJECTED", reason="BAD_STAGE")
        self.assertEqual(self.client.execute("takeoff"), ("REJECTED", "BAD_STAGE"))
        self.ros.on_command = lambda req: self.ros.status(req, "SUCCESS")
        self.assertEqual(self.client.execute("takeoff"), ("SUCCESS", ""))

    def test_wrong_correlations_are_not_stored(self):
        def command(req):
            for extra in ({"server_epoch": "old"}, {"session_id": "wrong"},
                          {"request_id": "wrong"}, {"command": "land"}):
                self.ros.status(req, "ACCEPTED", **extra)
            self.assertNotIn(req["request_id"], self.client.accepted)
            self.assertNotIn(req["request_id"], self.client.results)
            self.ros.status(req, "SUCCESS")
        self.ros.on_command = command
        self.assertEqual(self.client.execute("takeoff"), ("SUCCESS", ""))

    def test_timeout_lockout_no_resend_reconcile_is_separate(self):
        self.ros.on_command = lambda req: None
        with self.assertRaises(RuntimeError):
            self.client.execute("takeoff")
        req = self.ros.publishers["/mission_request"].messages[-1]
        with self.assertRaises(RuntimeError):
            self.client.execute("land")
        self.assertEqual(len(self.ros.publishers["/mission_request"].messages), 2)
        self.ros.ready(req["session_id"], last_request_id=req["request_id"], last_command="takeoff",
                       last_status="SUCCESS", last_reason="old outcome")
        with self.assertRaises(RuntimeError):
            self.client.execute("land")
        self.assertEqual(self.client.reconcile_pending(), ("SUCCESS", "old outcome"))
        self.assertFalse(self.client.uncertain)

    def test_wrong_ready_does_not_overwrite_current(self):
        ready = self.client.ready
        self.ros.ready("wrong", last_request_id="wrong", last_status="SUCCESS")
        self.assertIs(self.client.ready, ready)
        self.client.ready_received_at -= 3
        with self.assertRaises(RuntimeError):
            self.client.execute("takeoff")

    def test_missing_status_command_is_not_stored_or_authoritative(self):
        self.client.requests["pending"] = "takeoff"
        self.client.pending_request_id = "pending"
        for status in ("ACCEPTED", "SUCCESS", "REJECTED"):
            self.client._on_status(message(dict(protocol=1, server_epoch=self.client.epoch,
                session_id=self.client.session_id, request_id="pending", status=status)))
        self.assertNotIn("pending", self.client.accepted)
        self.assertNotIn("pending", self.client.results)
        self.assertIsNone(self.client.reconcile_pending())
        self.assertEqual(self.client.pending_request_id, "pending")

    def test_missing_ready_last_command_is_not_authoritative(self):
        self.client.requests["pending"] = "takeoff"
        self.client.pending_request_id = "pending"
        self.ros.ready(self.client.session_id, last_request_id="pending", last_status="SUCCESS")
        self.assertIsNone(self.client.reconcile_pending())
        self.assertEqual(self.client.pending_request_id, "pending")

    def test_reset_status_requires_explicit_empty_command(self):
        self.client.requests["reset"] = ""
        payload = dict(protocol=1, server_epoch=self.client.epoch, session_id=self.client.session_id,
                       request_id="reset", status="SUCCESS", reason="RESET")
        self.client._on_status(message(payload))
        self.assertIsNone(self.client._pop_result("reset"))
        payload["command"] = ""
        self.client._on_status(message(payload))
        self.assertEqual(self.client._pop_result("reset")["reason"], "RESET")

    def test_wrong_last_command_cannot_reconcile(self):
        self.client.requests["pending"] = "takeoff"
        self.client.pending_request_id = "pending"
        self.ros.ready(self.client.session_id, last_request_id="pending", last_command="land", last_status="SUCCESS")
        self.assertIsNone(self.client.reconcile_pending())

    def test_ctrl_c_in_wait_aborts_matching_request(self):
        self.ros.on_command = lambda req: self.ros.status(req, "ACCEPTED")
        with patch.object(mo.time, "sleep", side_effect=KeyboardInterrupt):
            with self.assertRaisesRegex(RuntimeError, "Interrupted"):
                self.client.execute("takeoff")
        req = self.ros.publishers["/mission_request"].messages[-1]
        abort = self.ros.publishers["/mission_abort"].messages[-1]
        for key in ("protocol", "server_epoch", "session_id", "request_id"):
            self.assertEqual(req[key], abort[key])
        self.assertIsNone(self.client.pending_request_id)

    def test_abort_timeout_keeps_lockout(self):
        self.client.requests["pending"] = "takeoff"
        self.client.pending_request_id = "pending"
        self.ros.on_abort = lambda req: None
        with patch.object(mo, "ABORT_TIMEOUT_S", 0.01):
            self.assertIsNone(self.client.abort_pending())
        self.assertTrue(self.client.uncertain)
        self.assertEqual(self.client.pending_request_id, "pending")

    def test_manual_emergency_requires_fresh_idle_and_is_separate(self):
        self.client.uncertain = True
        with self.assertRaisesRegex(RuntimeError, "Emergency land blocked"):
            self.client.execute("emergency_land")
        self.assertEqual(len(self.ros.publishers["/mission_request"].messages), 1)

    def test_emergency_settles_correlated_pending_before_send(self):
        self.client.requests["pending"] = "takeoff"
        self.client.pending_request_id = "pending"
        self.client.uncertain = True
        def abort(req):
            self.ros.status(req, "ABORTED", command="takeoff")
            self.ros.ready(self.client.session_id)
        self.ros.on_abort = abort
        self.assertEqual(self.client.execute("emergency_land"), ("SUCCESS", ""))
        commands = [item.get("command") for item in self.ros.publishers["/mission_request"].messages]
        self.assertEqual(commands[-1], "emergency_land")
        self.assertEqual(commands.count("emergency_land"), 1)

    def test_abort_terminal_without_new_ready_cannot_send_emergency(self):
        self.client.requests["pending"] = "takeoff"
        self.client.pending_request_id = "pending"
        self.ros.on_abort = lambda req: self.ros.status(req, "ABORTED", command="takeoff")
        with patch.object(mo, "ABORT_TIMEOUT_S", 0.01):
            with self.assertRaisesRegex(RuntimeError, "fresh nonbusy READY"):
                self.client.execute("emergency_land")
        self.assertEqual(len(self.ros.publishers["/mission_request"].messages), 1)

    def test_busy_ready_blocks_emergency_without_resend(self):
        self.client.ready["busy"] = True
        with self.assertRaises(RuntimeError):
            self.client.execute("emergency_land")
        self.assertEqual(len(self.ros.publishers["/mission_request"].messages), 1)

    def test_epoch_change_latches_identity_and_blocks_reset_or_movement(self):
        request = {"protocol": 1, "server_epoch": self.client.epoch,
                   "session_id": self.client.session_id, "request_id": "pending", "command": "takeoff"}
        self.client.requests["pending"] = "takeoff"
        self.client.pending_request_id = "pending"
        self.ros.ready(self.client.session_id, server_epoch="epoch-b", state="IDLE")
        self.assertEqual(self.client.controller_epoch_change["pending_request_id"], "pending")
        with self.assertRaisesRegex(RuntimeError, "Controller epoch changed"):
            self.client.execute("emergency_land")
        with self.assertRaisesRegex(RuntimeError, "Controller epoch changed"):
            self.client.execute("land")
        self.assertEqual(self.client.pending_request_id, request["request_id"])
        with self.assertRaisesRegex(RuntimeError, "Controller epoch changed"):
            self.client.initialize()
        self.ros.ready(self.client.session_id)
        with self.assertRaisesRegex(RuntimeError, "Controller epoch changed"):
            self.client.execute("land")
        self.assertEqual(len(self.ros.publishers["/mission_request"].messages), 1)

    def test_unknown_abort_preserves_prior_lockout_without_emergency(self):
        self.client.requests["old"] = "takeoff"
        self.client.pending_request_id = "old"
        self.client.uncertain = True
        self.ros.on_abort = lambda req: None
        with patch.object(mo, "ABORT_TIMEOUT_S", 0.01):
            with self.assertRaisesRegex(RuntimeError, "Emergency land blocked"):
                self.client.execute("emergency_land")
        self.assertEqual(len(self.ros.publishers["/mission_request"].messages), 1)
        self.assertEqual(self.client.pending_request_id, "old")
        self.assertTrue(self.client.uncertain)

    def test_recovery_state_only_allows_explicit_emergency(self):
        self.client.ready["state"] = "RECOVERY_REQUIRED"
        with self.assertRaises(RuntimeError):
            self.client.execute("land")
        self.assertEqual(self.client.execute("emergency_land"), ("SUCCESS", ""))

    def test_abort_rejection_with_empty_command_cannot_clear_pending(self):
        self.client.requests["pending"] = "takeoff"
        self.client.pending_request_id = "pending"
        self.client._on_status(message(dict(protocol=1, server_epoch=self.client.epoch,
            session_id=self.client.session_id, request_id="pending", command="", status="REJECTED")))
        self.assertIsNone(self.client.reconcile_pending())
        self.assertEqual(self.client.pending_request_id, "pending")

    def test_reset_requires_matching_fresh_ready(self):
        ros = Ros()
        ros.reset_ready = False
        with patch.object(mo, "rospy", ros):
            client = mo.MissionClient()
            ros.ready()
            original_wait = client._wait_for
            client._wait_for = lambda predicate, timeout: original_wait(predicate, 0.01)
            with self.assertRaises(RuntimeError):
                client.initialize()
            self.assertFalse(client.session_ready)
            with self.assertRaises(RuntimeError):
                client.execute("takeoff")


class OperatorTests(unittest.TestCase):
    def run_main(self, inputs, client):
        ros = types.SimpleNamespace(init_node=lambda *_a, **_k: None, sleep=lambda _s: None,
                                    is_shutdown=lambda: False)
        with patch.object(mo, "rospy", ros), patch.object(mo, "MissionClient", return_value=client), \
                patch.object(mo, "load_model", return_value=(None, None, [])), \
                patch("builtins.input", side_effect=inputs), patch("builtins.print"), \
                patch.object(mo, "generate_validated_commands", return_value="takeoff") as model:
            mo.main()
            return model

    def test_timeout_keeps_recovery_ui_and_explicit_reconcile(self):
        from unittest.mock import Mock
        client = Mock(uncertain=False, pending_request_id=None)
        def execute(command):
            client.uncertain = True
            client.pending_request_id = "old"
            raise RuntimeError("timeout")
        def reconcile():
            client.pending_request_id = None
            client.uncertain = False
            return "SUCCESS", "old request"
        client.execute.side_effect = execute
        client.reconcile_pending.side_effect = reconcile
        self.run_main(["起飞", "RUN", "land", "reconcile", "q"], client)
        client.execute.assert_called_once_with("takeoff")
        client.reconcile_pending.assert_called_once()

    def test_q_cannot_exit_with_unresolved_request(self):
        from unittest.mock import Mock
        client = Mock(uncertain=True, pending_request_id="pending")
        client.abort_pending.return_value = None
        def reconcile():
            client.pending_request_id = None
            client.uncertain = False
            return "ABORTED", "settled"
        client.reconcile_pending.side_effect = reconcile
        self.run_main(["q", "reconcile", "q"], client)
        client.abort_pending.assert_called_once()
        client.reconcile_pending.assert_called_once()

    def test_eof_keeps_callbacks_until_pending_settles(self):
        from unittest.mock import Mock
        client = Mock(uncertain=True, pending_request_id="pending")
        client.abort_pending.return_value = None
        def wait(predicate, timeout):
            self.assertEqual(client.pending_request_id, "pending")
            self.assertEqual(timeout, mo.ABORT_TIMEOUT_S)
            client.pending_request_id = None
            return "ABORTED", "delayed outcome"
        client._wait_for.side_effect = wait
        self.run_main([EOFError()], client)
        client.abort_pending.assert_called_once()
        client._wait_for.assert_called_once_with(client.reconcile_pending, mo.ABORT_TIMEOUT_S)

    def test_every_model_command_requires_run_confirmation(self):
        from unittest.mock import Mock
        client = Mock(uncertain=False, pending_request_id=None)
        client.execute.return_value = ("SUCCESS", "")
        model = self.run_main(["起飞", "cancel", "起飞", "RUN", "q"], client)
        self.assertEqual(model.call_count, 2)
        client.execute.assert_called_once_with("takeoff")

    def test_emergency_manual_confirmation_without_model(self):
        from unittest.mock import Mock
        client = Mock(uncertain=True, pending_request_id="old")
        def execute(command):
            client.pending_request_id = None
            client.uncertain = False
            return "SUCCESS", ""
        client.execute.side_effect = execute
        model = self.run_main(["emergency_land", "cancel", "emergency_land", "RUN", "q"], client)
        model.assert_not_called()
        client.execute.assert_called_once_with("emergency_land")


if __name__ == "__main__":
    unittest.main()
