"""Keep the YOLO/HSV detection window on and move it to the main thread.

The 'Detection + Color' window shows the square_frame and balloon bboxes, the
perception result window rule 4.4(5) requires for the frame and balloon
stages (5 points per stage when missing).  Two changes to det_color.py
(md5 9eda7268, official object_det package):
  * /object_detection/visualization/show_window defaults to true; a config
    that sets it false explicitly (e.g. a headless yaml) still wins;
  * the image callback only stores the annotated frame; run() owns
    imshow/waitKey on the main thread, so the window cannot delay detection.

Usage: python patch_det_color_window.py SOURCE OUTPUT [BACKUP_DIR]
"""
import hashlib
import pathlib
import shutil
import sys

EXPECTED_MD5 = "9eda726899abaf4f951f6b03a08c11ad"

REPLACEMENTS = [
    (
        "        self.show_visualization = rospy.get_param('/object_detection/visualization/show_window', False)\n",
        "        # det_window_main_thread_v1: window on by default (rule 4.4(5)), drawn by run().\n"
        "        self.show_visualization = rospy.get_param('/object_detection/visualization/show_window', True)\n"
        "        self._display_frame = None\n",
    ),
    (
        "        try:\n"
        "            if not hasattr(self, '_window_created'):\n"
        "                cv2.namedWindow('Detection + Color', cv2.WINDOW_NORMAL)\n"
        "                cv2.resizeWindow('Detection + Color', 640, 480)\n"
        "                self._window_created = True\n"
        "\n"
        "            cv2.imshow('Detection + Color', img_vis_rgb)\n"
        "            cv2.waitKey(2)\n"
        "        except Exception as e:\n"
        "            rospy.logwarn_throttle(5.0, f\"Display error: {e}\")\n",
        "        self._display_frame = img_vis_rgb\n",
    ),
    (
        "        rospy.loginfo(\"Object Detection + Color Node running (event-driven)...\")\n"
        "        try:\n"
        "            rospy.spin()\n",
        "        rospy.loginfo(\"Object Detection + Color Node running (event-driven)...\")\n"
        "        try:\n"
        "            if self.show_visualization:\n"
        "                self._display_loop()\n"
        "            rospy.spin()\n",
    ),
    (
        "    def run(self):\n",
        "    def _display_loop(self):\n"
        "        \"\"\"Own the OpenCV window on the main thread until shutdown.\"\"\"\n"
        "        shown = None\n"
        "        try:\n"
        "            cv2.namedWindow('Detection + Color', cv2.WINDOW_NORMAL)\n"
        "            cv2.resizeWindow('Detection + Color', 640, 480)\n"
        "            while not rospy.is_shutdown():\n"
        "                frame = self._display_frame\n"
        "                if frame is not None and frame is not shown:\n"
        "                    cv2.imshow('Detection + Color', frame)\n"
        "                    shown = frame\n"
        "                cv2.waitKey(30)\n"
        "        except Exception as e:\n"
        "            # A broken display must never stop detection publishing.\n"
        "            rospy.logerr(f\"Display loop failed, detection continues without window: {e}\")\n"
        "            self.show_visualization = False\n"
        "\n"
        "    def run(self):\n",
    ),
]


def patch(source: bytes) -> bytes:
    if hashlib.md5(source).hexdigest() != EXPECTED_MD5:
        raise ValueError("det_color.py MD5 differs from the reviewed official version; no changes made")
    text = source.decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    text = text.replace("\r\n", "\n")
    for old, new in REPLACEMENTS:
        if text.count(old) != 1:
            raise ValueError("anchor not found exactly once; no changes made:\n" + old)
        text = text.replace(old, new, 1)
    return text.replace("\n", newline).encode("utf-8")


if __name__ == "__main__":
    source = pathlib.Path(sys.argv[1])
    output = pathlib.Path(sys.argv[2])
    original = source.read_bytes()
    patched = patch(original)
    if len(sys.argv) > 3:
        backup_dir = pathlib.Path(sys.argv[3])
        backup_dir.mkdir(parents=True, exist_ok=False)
        shutil.copy2(source, backup_dir / "det_color.py")
        (backup_dir / "restore.sh").write_text(
            "#!/usr/bin/env bash\nset -e\n"
            f"cp -p \"{(backup_dir / 'det_color.py').resolve()}\" \"{source.resolve()}\"\n"
            f"md5sum \"{source.resolve()}\"  # expect {EXPECTED_MD5}\n",
            encoding="utf-8")
    output.write_bytes(patched)
    print(f"{EXPECTED_MD5} -> {hashlib.md5(patched).hexdigest()}")
