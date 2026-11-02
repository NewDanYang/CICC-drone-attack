import json, os, sys, glob
import numpy as np, cv2

d = sys.argv[1]
out = []
for p in sorted(glob.glob(os.path.join(d, "images", "*.png"))):
    img = cv2.imread(p)
    if img is None:
        continue
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    # purple balloon in UE: high saturation, hue around 140-160 (OpenCV scale)
    mask = cv2.inRange(hsv, (128, 60, 50), (168, 255, 255))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    best = None
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        if a < 40:
            continue
        if w < 6 or h < 6:
            continue
        score = a
        if best is None or score > best[4]:
            best = (int(x), int(y), int(x + w), int(y + h), int(a))
    row = {"image": os.path.basename(p), "gt": best}
    out.append(row)
with open(os.path.join(d, "hsv_gt.jsonl"), "w") as f:
    for r in out:
        f.write(json.dumps(r) + "\n")
found = sum(1 for r in out if r["gt"])
print("images", len(out), "with_purple_blob", found)
for r in out[:10]:
    print(r)
