#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ArUco marker detection ROS node (Python version)

Drop-in replacement for aruco_detect_node (C++).
Identical service/topic interface:
  Service  : /aruco/enable  (std_srvs/SetBool)  -- enable/disable detection
  Publisher: /aruco/detected_id (std_msgs/Int32) -- detected marker ID
  Publisher: /aruco/debug_image (sensor_msgs/Image) -- optional debug image
  Subscriber: ~image_topic param (default /rflysim/sensor2/img_rgb)

Diagnostics note: this build counts every image callback execution and reports
the rate once per second, deliberately WITHOUT a log throttle, so that a
callback that stops being scheduled is visible directly. Earlier investigations
could only infer callback starvation from the absence of throttled messages;
this makes it a measurement.
"""

import rospy
import cv2
import numpy as np
from sensor_msgs.msg import Image
from std_msgs.msg import Int32
from std_srvs.srv import SetBool, SetBoolResponse

# --- cv_bridge: pure-numpy fallback (Boost.Python conflict on Python 3.9+) ---
try:
    from cv_bridge import CvBridge as _CvBridge
    _CV_BRIDGE_OK = True
except Exception:
    _CV_BRIDGE_OK = False


def _imgmsg_to_numpy(msg: Image) -> np.ndarray:
    """Zero-copy ROS Image -> numpy array without cv_bridge C++ extension."""
    enc = msg.encoding.lower()
    dtype_map = {
        "rgb8":   (np.uint8,   3), "bgr8":   (np.uint8,   3),
        "rgba8":  (np.uint8,   4), "bgra8":  (np.uint8,   4),
        "mono8":  (np.uint8,   1), "8uc1":   (np.uint8,   1),
        "mono16": (np.uint16,  1), "16uc1":  (np.uint16,  1),
        "32fc1":  (np.float32, 1),
    }
    if enc in dtype_map:
        dtype, channels = dtype_map[enc]
        arr = np.frombuffer(msg.data, dtype=dtype)
        arr = arr.reshape(msg.height, msg.width) if channels == 1 \
              else arr.reshape(msg.height, msg.width, channels)
        if enc == "rgb8":
            arr = arr[:, :, ::-1].copy()
        elif enc == "rgba8":
            arr = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
        elif enc == "bgra8":
            arr = cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
        return arr
    elif _CV_BRIDGE_OK:
        return _CvBridge().imgmsg_to_cv2(msg, "bgr8")
    raise ValueError(f"Unsupported encoding: {msg.encoding}")


def _numpy_to_imgmsg(arr: np.ndarray, header, encoding="bgr8") -> Image:
    """numpy array -> ROS Image (no cv_bridge needed)."""
    if _CV_BRIDGE_OK:
        return _CvBridge().cv2_to_imgmsg(arr, encoding)
    msg = Image()
    msg.header = header
    msg.height, msg.width = arr.shape[:2]
    msg.encoding = encoding
    msg.step = arr.strides[0]
    msg.data = arr.tobytes()
    return msg


# ---------------------------------------------------------------------------

class ArucoDetectNode:
    def __init__(self):
        rospy.init_node("aruco_detect_node", anonymous=False)

        # --- params ---
        self.image_topic  = rospy.get_param("~image_topic", "/rflysim/sensor2/img_rgb")
        dict_id           = rospy.get_param("~dictionary_id", 16)  # DICT_ARUCO_ORIGINAL = 16
        self.show_debug   = rospy.get_param("~show_debug", False)
        self.save_dir     = rospy.get_param("~save_dir", "")
        enabled_default   = rospy.get_param("~enabled_default", False)

        # Detection preprocessing. Measured against real competition frames
        # (84 frames captured from a failing run, marker ~180 px wide):
        #   shipped defaults        -> 13 frames detected, first at frame 54
        #   2x upscale + subpix     ->  6 frames, first at 62   (REGRESSION,
        #                              deployed in error on 2026-10-06)
        #   CLAHE + 2x + subpix     -> 25 frames
        #   CLAHE + 3x + subpix     -> 27 frames  <-- selected
        # So: CLAHE helps materially; the bare upscale does not. Both are
        # params so they can be turned off without editing code.
        self.use_clahe    = bool(rospy.get_param("~use_clahe", True))
        self.upscale      = float(rospy.get_param("~upscale", 3.0))
        self.use_subpix   = bool(rospy.get_param("~use_subpix", True))
        self.debug_display = bool(rospy.get_param("~debug_display", False))
        self.queue_size   = max(1, int(rospy.get_param("~queue_size", 1)))

        # --- ArUco detector ---
        aruco_dict = cv2.aruco.getPredefinedDictionary(dict_id)
        self.params = cv2.aruco.DetectorParameters_create()
        if self.use_subpix:
            self.params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
            self.params.cornerRefinementWinSize = 5
            self.params.cornerRefinementMaxIterations = 30
            self.params.cornerRefinementMinAccuracy = 0.1

        self.aruco_dict = aruco_dict
        self.clahe = (cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                      if self.use_clahe else None)

        # --- state ---
        self.enabled       = enabled_default
        self.has_detection = False
        self.img_sub       = None   # dynamically managed

        # --- diagnostics: unthrottled counters, reported once per second ---
        self.n_callbacks   = 0
        self.n_decode_fail = 0
        self._last_report  = rospy.Time.now()
        self._last_count   = 0
        # A Timer reports even when the image callback is not being scheduled.
        # This turns the previously indirect "no Searching lines" symptom into
        # an explicit callbacks/s=0 measurement.
        self._rate_timer = rospy.Timer(rospy.Duration(1.0), self._rate_timer_cb)

        # --- publishers / services ---
        self.id_pub        = rospy.Publisher("/aruco/detected_id", Int32, queue_size=10)
        self.debug_img_pub = rospy.Publisher("/aruco/debug_image", Image, queue_size=1)
        self.enable_srv    = rospy.Service("/aruco/enable", SetBool, self._enable_cb)

        if self.enabled:
            self._subscribe()

        rospy.loginfo("=" * 42)
        rospy.loginfo("[ArucoDetectNode] Python node started")
        rospy.loginfo("[ArucoDetectNode] Image topic : %s", self.image_topic)
        rospy.loginfo("[ArucoDetectNode] Dictionary  : %d (DICT_ARUCO_ORIGINAL=16, DICT_6X6_250=10)", dict_id)
        rospy.loginfo("[ArucoDetectNode] Preprocess  : clahe=%s upscale=%.2fx subpix=%s",
                      self.use_clahe, self.upscale, self.use_subpix)
        rospy.loginfo("[ArucoDetectNode] Debug window: %s", self.debug_display)
        rospy.loginfo("[ArucoDetectNode] Queue size  : %d", self.queue_size)
        rospy.loginfo("[ArucoDetectNode] Detection   : %s",
                      "ENABLED" if self.enabled else "DISABLED (call /aruco/enable)")
        rospy.loginfo("=" * 42)

    # ------------------------------------------------------------------ subscribe
    def _subscribe(self):
        if self.img_sub is None:
            self.img_sub = rospy.Subscriber(
                self.image_topic, Image, self._image_cb, queue_size=self.queue_size)
            rospy.loginfo("[ArucoDetectNode] Subscribed to %s", self.image_topic)

    def _unsubscribe(self):
        if self.img_sub is not None:
            self.img_sub.unregister()
            self.img_sub = None
            rospy.loginfo("[ArucoDetectNode] Unsubscribed (saving CPU)")

    def _deferred_unsubscribe(self, _event=None):
        """Unsubscribe via Timer so it runs OUTSIDE the image callback.
        Calling unregister() from within its own callback causes a ROS error."""
        self._unsubscribe()
        rospy.loginfo("[ArucoDetectNode] Detection auto-disabled after success (saving CPU)")

    # ------------------------------------------------------------------ service
    def _enable_cb(self, req):
        self.enabled       = req.data
        self.has_detection = False
        if self.enabled:
            self.n_callbacks = 0
            self.n_decode_fail = 0
            self._last_report = rospy.Time.now()
            self._last_count = 0
            self._subscribe()
            rospy.loginfo("[ArucoDetectNode] >>> Detection ENABLED <<<")
            return SetBoolResponse(success=True, message="ArUco detection enabled")
        else:
            self._unsubscribe()
            rospy.loginfo("[ArucoDetectNode] >>> Detection DISABLED <<< (callbacks=%d decode_fail=%d)",
                          self.n_callbacks, self.n_decode_fail)
            return SetBoolResponse(success=True, message="ArUco detection disabled")

    # ------------------------------------------------------------------ detection
    def _preprocess(self, gray):
        g = gray
        if self.clahe is not None:
            g = self.clahe.apply(g)
        if self.upscale and self.upscale != 1.0:
            g = cv2.resize(g, None, fx=self.upscale, fy=self.upscale,
                           interpolation=cv2.INTER_CUBIC)
        return g

    def _report_rate(self):
        """Log callback rate once per second, deliberately unthrottled so that
        a stalled callback is directly visible in the log."""
        now = rospy.Time.now()
        dt = (now - self._last_report).to_sec()
        if dt <= 0.0:
            return
        delta = self.n_callbacks - self._last_count
        rospy.loginfo("[ArucoDetectNode] callbacks/s=%.1f total=%d decode_fail=%d enabled=%s",
                      delta / dt, self.n_callbacks, self.n_decode_fail, self.enabled)
        self._last_report = now
        self._last_count = self.n_callbacks

    def _rate_timer_cb(self, _event=None):
        """Report from a Timer thread so callback starvation is observable."""
        if self.enabled:
            self._report_rate()

    # ------------------------------------------------------------------ image cb
    def _image_cb(self, msg: Image):
        if not self.enabled:
            return
        self.n_callbacks += 1

        try:
            bgr = _imgmsg_to_numpy(msg)
        except Exception as e:
            self.n_decode_fail += 1
            rospy.logerr_throttle(1.0, "[ArucoDetectNode] Image decode error: %s", e)
            return

        if bgr is None or bgr.size == 0:
            self.n_decode_fail += 1
            return

        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        try:
            det_gray = self._preprocess(gray)
            corners, ids, rejected = cv2.aruco.detectMarkers(
                det_gray, self.aruco_dict, parameters=self.params)
        except Exception as e:
            rospy.logerr_throttle(1.0, "[ArucoDetectNode] detectMarkers error: %s", e)
            return

        if self.upscale and self.upscale != 1.0 and corners:
            corners = [c / self.upscale for c in corners]

        detected = ids is not None and len(ids) > 0

        # --- publish result FIRST: a debug-drawing/display failure must never
        # be able to suppress a real detection. ---
        if detected:
            marker_id = int(ids[0][0])
            self.id_pub.publish(Int32(data=marker_id))
            self.has_detection = True

            rospy.loginfo("\033[1;33m+==========================================+\033[0m")
            rospy.loginfo("\033[1;33m|  \033[1;32m*** ArUco Marker Detected! ***\033[1;33m        |\033[0m")
            rospy.loginfo("\033[1;33m|    \033[1;37mDetected ID: \033[1;36m%-4d\033[1;33m                    |\033[0m",
                          marker_id)
            rospy.loginfo("\033[1;33m+==========================================+\033[0m")

            self.enabled = False
            rospy.Timer(rospy.Duration(0.05), self._deferred_unsubscribe, oneshot=True)
        else:
            rospy.loginfo_throttle(2.0,
                "[ArucoDetectNode] Searching... no marker found (rejected: %d)",
                len(rejected) if rejected else 0)

        # --- debug draw/display/save: best-effort, never raises out of the
        # callback. The interactive window is OFF by default: at 10 Hz the
        # imshow/waitKey pair runs on the same thread that must service the
        # image subscription, which is the prime suspect for the observed
        # callback starvation. Use ~debug_display:=true only when watching by
        # eye, not during timed trials.
        need_debug = self.debug_display or self.debug_img_pub.get_num_connections() > 0
        if need_debug or detected:
            try:
                dbg = bgr.copy()
                if detected:
                    cv2.aruco.drawDetectedMarkers(dbg, corners, ids)
                if need_debug:
                    if rejected:
                        for r in rejected:
                            pts = (r.reshape(-1, 1, 2) / self.upscale).astype(np.int32)
                            cv2.polylines(dbg, [pts], True, (0, 0, 255), 1)
                    status = (f"ID: {int(ids[0][0])}" if detected
                              else f"NO MATCH (rej: {len(rejected) if rejected else 0})")
                    cv2.putText(dbg, status, (10, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                                (0, 255, 0) if detected else (0, 0, 255), 2)
                    if self.debug_img_pub.get_num_connections() > 0:
                        self.debug_img_pub.publish(_numpy_to_imgmsg(dbg, msg.header))
                    if self.debug_display:
                        cv2.imshow("ArUco Detection (Python)", dbg)
                        cv2.waitKey(1)
                if detected and self.save_dir and need_debug:
                    path = f"{self.save_dir}/aruco_id_{marker_id}.jpg"
                    cv2.imwrite(path, dbg)
                    rospy.loginfo("[ArucoDetectNode] Image saved: %s", path)
            except Exception as e:
                rospy.logerr_throttle(1.0, "[ArucoDetectNode] debug draw/display error: %s", e)

    # ------------------------------------------------------------------ run
    def run(self):
        rospy.spin()
        if self.debug_display:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    try:
        node = ArucoDetectNode()
        node.run()
    except rospy.ROSInterruptException:
        pass
    except Exception as e:
        rospy.logerr("[ArucoDetectNode] Fatal: %s", e)
        import traceback
        traceback.print_exc()
