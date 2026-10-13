"""Offline test of ArucoDetectNode.run() main-thread display loop.

rospy, sensor_msgs, std_msgs, std_srvs and the cv2 GUI calls are stubbed.
Run: python test_aruco_display_loop.py
"""
import importlib.util
import pathlib
import sys
import types

NODE = pathlib.Path(__file__).resolve().parents[2] / "aruco" / "aruco_detect_node.py"

rospy = types.ModuleType("rospy")
state = {"ticks": 0, "limit": 0, "spun": 0, "errors": []}


def is_shutdown():
    state["ticks"] += 1
    return state["ticks"] > state["limit"]


rospy.is_shutdown = is_shutdown
rospy.spin = lambda: state.__setitem__("spun", state["spun"] + 1)
rospy.logerr = lambda *a: state["errors"].append(a)
rospy.ROSInterruptException = Exception
sys.modules["rospy"] = rospy
for name, attrs in {"sensor_msgs": {}, "sensor_msgs.msg": {"Image": object},
                    "std_msgs": {}, "std_msgs.msg": {"Int32": object},
                    "std_srvs": {}, "std_srvs.srv": {"SetBool": object, "SetBoolResponse": object}}.items():
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    sys.modules[name] = mod

cv2 = types.ModuleType("cv2")
gui = {"shown": [], "waits": 0, "destroyed": 0, "raise": False}


def imshow(name, frame):
    if gui["raise"]:
        raise RuntimeError("cannot connect to X server")
    gui["shown"].append(frame)


cv2.imshow = imshow
cv2.waitKey = lambda ms: gui.__setitem__("waits", gui["waits"] + 1)
cv2.destroyAllWindows = lambda: gui.__setitem__("destroyed", gui["destroyed"] + 1)
sys.modules["cv2"] = cv2
sys.modules["numpy"] = types.ModuleType("numpy")
sys.modules["numpy"].ndarray = object

spec = importlib.util.spec_from_file_location("aruco_node", NODE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.time.sleep = lambda s: None

failures = []


def check(label, cond):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


def fresh(display, frames_by_tick=None, limit=6):
    node = mod.ArucoDetectNode.__new__(mod.ArucoDetectNode)
    node.debug_display = display
    node._display_frame = None
    state.update(ticks=0, limit=limit, spun=0, errors=[])
    gui.update(shown=[], waits=0, destroyed=0)
    if frames_by_tick:
        real = rospy.is_shutdown

        def feeding():
            done = real()
            if state["ticks"] in frames_by_tick:
                node._display_frame = frames_by_tick[state["ticks"]]
            return done

        rospy.is_shutdown = feeding
        try:
            node.run()
        finally:
            rospy.is_shutdown = real
    else:
        node.run()
    return node


fresh(display=False)
check("window disabled: plain rospy.spin, no GUI calls", state["spun"] == 1 and not gui["shown"] and gui["waits"] == 0)

a, b = object(), object()
fresh(display=True, frames_by_tick={2: a, 4: b}, limit=6)
check("each new frame shown exactly once", gui["shown"] == [a, b])
check(f"no waitKey before first frame, then one per tick (got {gui['waits']})", gui["waits"] == 5)  # ticks 2..6
check("last frame stays (no re-show while unchanged)", gui["shown"][-1] is b and len(gui["shown"]) == 2)
check("window destroyed on shutdown", gui["destroyed"] == 1 and state["spun"] == 0)

gui["raise"] = True
node = fresh(display=True, frames_by_tick={1: a}, limit=3)
gui["raise"] = False
check("display failure falls back to spin with error log", state["spun"] == 1 and state["errors"] and node.debug_display is False)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
