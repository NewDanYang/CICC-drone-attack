"""Patchers against the exact bytes running on the server.

The server's mission_once.py (MD5 dcc050dd...) is the repo's
v3_stability/hit_balloon_v2/deployed_source/mission_once.before_color_guard.py
saved with CRLF; bt_ros.cpp (f3883b30...) is the official baseline file.
"""
import ast
import hashlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
V8 = REPO / 'v8_fm9g_scene'
sys.path.insert(0, str(V8 / 'patches'))
import patch_bt_ros          # noqa: E402
import patch_mission_once    # noqa: E402
import pytest                # noqa: E402

LIVE_SRC = REPO / 'v3_stability/hit_balloon_v2/deployed_source/mission_once.before_color_guard.py'
BT_SRC = REPO / 'official_baseline/catkin_ws/src/mission_pkg/src/bt_ros.cpp'
pytestmark = pytest.mark.skipif(not (LIVE_SRC.exists() and BT_SRC.exists()),
                                reason='needs the full repository checkout (baseline source copies)')

LIVE_MISSION_MD5 = 'dcc050dd1daa1792a7312345932d0fcb'


def live_mission_bytes():
    src = LIVE_SRC.read_bytes()
    core = src.lstrip(b'\xef\xbb\xbf').replace(b'\r\n', b'\n')
    data = core.replace(b'\n', b'\r\n')
    assert hashlib.md5(data).hexdigest() == LIVE_MISSION_MD5
    return data


def test_mission_patch_on_live_bytes():
    template = (V8 / 'patches/entry_main.py.txt').read_text(encoding='utf-8')
    out, changed = patch_mission_once.patch(live_mission_bytes(), template)
    assert changed == ['generate_commands', 'load_model']
    assert b'\r\n' in out and b'\r\r\n' not in out and out.count(b'\n') == out.count(b'\r\n')
    text = out.decode('utf-8')
    assert text.count('sampling=False, stream=False') == 2 and 'sampling=True' not in text
    assert 'stream=True' not in text
    tree = ast.parse(text)
    names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    assert names == ['load_model', 'generate_commands', 'main']
    # the entry falls back to generate_commands when no colour guard exists
    assert 'globals().get("generate_validated_commands") or generate_commands' in text


def test_bt_patch_on_live_bytes():
    src = BT_SRC.read_bytes()
    if hashlib.md5(src).hexdigest() != patch_bt_ros.OFFICIAL_MD5:
        # a checkout with autocrlf/eol conversion (seen on the server in round 2)
        src = src.replace(b'\r\n', b'\n')
    if hashlib.md5(src).hexdigest() != patch_bt_ros.OFFICIAL_MD5:
        pytest.skip('repo copy of bt_ros.cpp differs from the live baseline bytes')
    out = patch_bt_ros.patch(src)
    # deterministic output (server dry-run of the earlier timeouts gave deac4a1b...)
    assert hashlib.md5(out).hexdigest() == '18a8457fe4f204b4fd12fd32e81dceef'
