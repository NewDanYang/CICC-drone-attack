"""Run the patched live mission_once.py main() with stubbed torch/transformers/rospy
and a fake model: checks command publication, greedy flags, bridge construction,
and that argv mode exits on /mission_result."""
import sys
import threading
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_patches as tp   # noqa: E402

pytestmark = tp.pytestmark

COMMANDS = "takeoff\ncross_frame\ndetect_aruco\nreturn_cross_frame\nhit_balloon:red\nland"


class FakeModel:
    def __init__(self, fail_first=0):
        self.calls = []
        self.fail_first = fail_first

    def eval(self):
        return self

    def cuda(self):
        return self

    def chat(self, image=None, msgs=None, tokenizer=None, sampling=None, stream=None, **kw):
        # same constraint as FM9G4B-V modeling_fm9gv.py:319 (found on the server)
        assert sampling or not stream, "if use stream mode, make sure sampling=True"
        self.calls.append(sampling)
        if len(msgs) == 1:
            text = "好的"
        elif self.fail_first > 0:
            self.fail_first -= 1
            text = "好的，请描述您的任务需求。"
        else:
            text = "```command\n" + COMMANDS + "\n```"
        return iter([text]) if stream else text


GREEDY = True  # unused; params on the fixture decide


@pytest.fixture(params=[(True, 0), (False, 1)], ids=['greedy', 'sampling+retry'])
def env(tmp_path, monkeypatch, request):
    greedy, fail_first = request.param
    model = FakeModel(fail_first)
    published, subs = [], {}
    tf = types.ModuleType('transformers')
    tf.AutoModel = types.SimpleNamespace(from_pretrained=lambda *a, **k: model)
    tf.AutoTokenizer = types.SimpleNamespace(from_pretrained=lambda *a, **k: object())
    tf.AutoProcessor = types.SimpleNamespace(from_pretrained=lambda *a, **k: object())
    torch = types.ModuleType('torch')
    torch.bfloat16 = 'bf16'
    torch.cuda = types.SimpleNamespace(empty_cache=lambda: None)
    torch.set_num_threads = torch.set_num_interop_threads = lambda n: None
    rospy = types.ModuleType('rospy')
    state = {'shutdown': False}
    rospy.init_node = lambda *a, **k: None
    rospy.sleep = lambda s: None
    rospy.loginfo = lambda *a, **k: None
    rospy.is_shutdown = lambda: state['shutdown']

    class Pub:
        def __init__(self, topic, *a, **k):
            self.topic = topic

        def publish(self, m):
            published.append((self.topic, m.data))
    rospy.Publisher = Pub
    std = types.ModuleType('std_msgs.msg')
    std.String = lambda data='': types.SimpleNamespace(data=data)
    built = {}

    class FakeScene:
        def __init__(self, *a):
            built['scene'] = a
            self.result_seen = False
            # simulate the mission finishing shortly after the command is published
            threading.Timer(0.3, lambda: setattr(self, 'result_seen', True)).start()

        def close(self):
            built['closed'] = True
    scene_mod = types.ModuleType('fm9g_scene.bridge')
    scene_mod.SceneBridge = FakeScene
    pres_mod = types.ModuleType('fm9g_scene.presence')
    pres_mod.FastPresence = lambda *a, **k: 'fp'
    for name, mod in {'transformers': tf, 'torch': torch, 'rospy': rospy, 'std_msgs': types.ModuleType('std_msgs'),
                      'std_msgs.msg': std, 'fm9g_scene': types.ModuleType('fm9g_scene'),
                      'fm9g_scene.bridge': scene_mod, 'fm9g_scene.presence': pres_mod}.items():
        monkeypatch.setitem(sys.modules, name, mod)
    (tmp_path / 'prompts').mkdir()
    (tmp_path / 'prompts' / 'mission_prompt.txt').write_text('PROMPT', encoding='utf-8')
    template = (tp.V8 / 'patches/entry_main.py.txt').read_text(encoding='utf-8')
    out, _ = tp.patch_mission_once.patch(tp.live_mission_bytes(), template, greedy=greedy)
    path = tmp_path / 'mission_once.py'
    path.write_bytes(out)
    return types.SimpleNamespace(path=path, model=model, published=published, built=built,
                                 greedy=greedy, fail_first=fail_first)


def test_patched_entry_publishes_and_exits(env, monkeypatch):
    code = compile(env.path.read_bytes().decode('utf-8'), str(env.path), 'exec')
    g = {'__name__': 'mission_once_test', '__file__': str(env.path)}
    exec(code, g)
    monkeypatch.setattr(sys, 'argv', ['mission_once.py', '起飞，穿过框，识别二维码，再穿回来，打红色气球，降落'])
    t = threading.Thread(target=g['main'], daemon=True)
    t.start()
    t.join(timeout=10)
    assert not t.is_alive(), 'argv mode did not exit after mission_result'
    assert env.published == [('/mission_command', COMMANDS)]
    if env.greedy:
        assert env.model.calls == [False, False]      # init + command, both greedy
    else:
        assert env.model.calls == [True, True, True]  # init, failed reply, retry
    assert 'scene' in env.built and env.built.get('closed')
