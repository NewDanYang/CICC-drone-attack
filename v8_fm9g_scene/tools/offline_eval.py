#!/usr/bin/env python3
"""Offline evaluation of the FM9G scene pipeline on captured real frames.  No flight.

Runs exactly the flight decision path (fm9g_scene.model_io + fm9g_scene.pipeline)
on frames recorded by capture_scene.py, and scores it against references that are
used OFFLINE ONLY and never enter the flight path:
  square_frame : official YOLO best.pt (class 'square_frame', conf >= 0.5)
  aruco_marker : OpenCV ArUco DICT_ARUCO_ORIGINAL with CLAHE (AGENTS.md §4.2 setting)
  pillar, landing_pad : no automatic reference -> labels.jsonl if given, plus
                        contact sheets for a human to judge.

Run in the conda env on the server (GPU):
  /opt/conda/envs/demo/bin/python3 offline_eval.py --capture <dir> --out <new dir> \
      [--legacy-sweep] [--simulate-balloon-processor] [--labels labels.jsonl]
"""
import argparse
import json
import statistics as st
import sys
import time
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'code'))
from fm9g_scene import geometry as geo          # noqa: E402
from fm9g_scene.model_io import SceneModel      # noqa: E402
from fm9g_scene.pipeline import localise, select_candidates   # noqa: E402
from fm9g_scene.targets import TARGETS          # noqa: E402

CAMERA_TARGETS = {'front': ['square_frame', 'pillar'], 'down': ['aruco_marker', 'landing_pad']}
LEGACY_PROMPT = "这张图片里有没有方形穿越框？只回答“是”或“否”。"   # 6.2 frame_locator.py


# ------------------------------------------------------------- references
class YoloRef:
    def __init__(self, ws):
        sys.path.insert(0, str(Path(ws) / 'src/object_det/third_party'))
        from ultralytics import YOLO
        self.m = YOLO(str(Path(ws) / 'src/object_det/models/best.pt'))

    def __call__(self, bgr):
        r = self.m.predict(bgr, conf=0.5, verbose=False)[0]
        out = [b.xyxy[0].tolist() for b in r.boxes if r.names[int(b.cls)] == 'square_frame']
        return max(out, key=lambda b: (b[2] - b[0]) * (b[3] - b[1])) if out else None


def aruco_ref(bgr):
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    gray = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_ARUCO_ORIGINAL)
    try:
        corners, ids, _ = cv2.aruco.ArucoDetector(d, cv2.aruco.DetectorParameters()).detectMarkers(gray)
    except AttributeError:
        corners, ids, _ = cv2.aruco.detectMarkers(gray, d)
    if ids is None:
        return None
    c = corners[0].reshape(-1, 2) / 3.0
    return [float(c[:, 0].min()), float(c[:, 1].min()), float(c[:, 0].max()), float(c[:, 1].max())]


# ------------------------------------------------------------------ model
def load(model_dir):
    import torch
    from transformers import AutoModel, AutoTokenizer, AutoProcessor
    model = AutoModel.from_pretrained(model_dir, trust_remote_code=True, attn_implementation='sdpa',
                                      torch_dtype=torch.bfloat16).eval().cuda()
    tok = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True)
    proc = getattr(model, 'processor', None) or AutoProcessor.from_pretrained(
        model_dir, trust_remote_code=True, local_files_only=True)
    return model, tok, proc


def legacy_sweep_box(presence, bgr):
    """6.2 frame_locator.localize(), verbatim control flow, for the A/B record."""
    p = presence
    tile = 224
    xs = np.linspace(0, 640 - tile, 5).astype(int)
    ys = np.linspace(0, 480 - tile, 3).astype(int)
    windows = [(int(x), int(y), int(x) + tile, int(y) + tile) for y in ys for x in xs]
    probs = p.call(p.crops(bgr, windows), LEGACY_PROMPT, 1, 'eval', 'frame', 'frame', 0, 0, 'acquire_tiles', windows)
    positive = [w for w, pr in zip(windows, probs) if pr >= 0.5]
    if not positive:
        return None, 0.0
    best = windows[int(np.argmax(probs))]
    group = [w for w in positive if min(w[2], best[2]) > max(w[0], best[0]) and min(w[3], best[3]) > max(w[1], best[1])]
    roi = (max(w[0] for w in group), max(w[1] for w in group), min(w[2] for w in group), min(w[3] for w in group))
    if roi[2] - roi[0] < 48 or roi[3] - roi[1] < 48:
        roi = best
    for window in (p.square((roi[0] + roi[2]) / 2, (roi[1] + roi[3]) / 2, max(roi[2] - roi[0], roi[3] - roi[1], 128)),
                   tuple(best)):
        images, positions = p.sweep_imgs(bgr, window, p.n_initial)
        pr = p.call(images, LEGACY_PROMPT, 1, 'eval', 'frame', 'frame', 0, 0, 'acquire_sweep', [window])
        box, p0, _ = p.edge_box(pr, positions, window, (0.5,) * 4)
        if box:
            return box, p0
    return None, 0.0


# ----------------------------------------------------------------- report
def summarize(rows):
    out = {}
    for tgt in sorted({r['target'] for r in rows}):
        rs = [r for r in rows if r['target'] == tgt]
        acc = [r for r in rs if r['accepted']]
        has_ref = [r for r in rs if r.get('ref') is not None]
        tp = [r for r in acc if r.get('iou') is not None and r['iou'] >= 0.5]
        mis = [r for r in acc if r.get('ref') is not None and (r.get('iou') or 0) < 0.5]
        fp = [r for r in acc if r.get('ref_known') and r.get('ref') is None]
        wl = [r['world'] for r in acc if r.get('world') is not None]
        worlds = np.array(wl) if wl else np.zeros((0, 3))
        out[tgt] = {
            'frames': len(rs), 'accepted': len(acc),
            'reference_present': len(has_ref),
            'tp_iou50': len(tp), 'mislocalised_iou<0.5': len(mis), 'fp_no_reference': len(fp),
            'recall_vs_reference': (len(tp) / len(has_ref)) if has_ref else None,
            'median_iou_accepted': st.median([r['iou'] for r in acc if r.get('iou') is not None]) if tp or mis else None,
            'median_center_err_px': st.median([r['center_err'] for r in acc if r.get('center_err') is not None]) if tp or mis else None,
            'world_std_m': worlds.std(axis=0).round(3).tolist() if len(worlds) > 1 else None,
            'world_median': np.median(worlds, axis=0).round(3).tolist() if len(worlds) else None,
            'median_latency_s': st.median([r['latency_s'] for r in rs]),
            'reject_reasons': {k: sum(1 for r in rs for c in r['candidates'] if c.get('reject') == k)
                               for k in {c.get('reject') for r in rs for c in r['candidates'] if c.get('reject')}},
        }
        legacy = [r for r in rs if 'legacy' in r]
        if legacy:
            lb = [r['legacy'] for r in legacy if r['legacy']['box'] is not None]
            out[tgt]['legacy_sweep'] = {
                'frames': len(legacy), 'boxes': len(lb),
                'p0>=0.7': sum(1 for b in lb if b['p0'] >= 0.7),
                'iou>=0.5_vs_ref': sum(1 for b in lb if (b.get('iou') or 0) >= 0.5),
                'median_size_ratio_vs_ref': st.median([b['size_ratio'] for b in lb if b.get('size_ratio')]) if any(b.get('size_ratio') for b in lb) else None,
            }
    # Down-camera convention check (geometry.DOWN_CAM_R).  The marker is static,
    # so its estimated ground position must not move when the drone moves.  Any
    # wrong image-axis convention (rotation OR mirror) makes the estimate move
    # with the drone, but a mirror only shows up for translation along the
    # mirrored body axis, so both body axes need >= 0.3 m of translation
    # among the samples (the GoTo {aruco_hover} correction and the hover /
    # return-turn passes provide this).  Uses the OpenCV reference box only.
    aru = [r for r in rows if r['target'] == 'aruco_marker' and r.get('ref_world')]
    if len(aru) >= 2:
        W = np.array([r['ref_world'][:2] for r in aru])
        P = np.array([r['pos'][:2] for r in aru])
        Y = np.array([r['yaw'] for r in aru])
        med = np.median(W, axis=0)
        spread = float(np.percentile(np.hypot(*(W - med).T), 90))
        # drone displacement from the marker, expressed in body axes
        d = P - med
        bx = d[:, 0] * np.cos(Y) + d[:, 1] * np.sin(Y)
        by = -d[:, 0] * np.sin(Y) + d[:, 1] * np.cos(Y)
        rng = [float(np.ptp(bx)), float(np.ptp(by))]
        verdict = ('INSUFFICIENT pose diversity (need >=0.3 m along both body axes)' if min(rng) < 0.3 else
                   'PASS' if spread < 0.10 else 'FAIL: fix geometry.DOWN_CAM_R before flight')
        out['down_camera_convention'] = {'samples': len(aru), 'marker_world_median': med.round(3).tolist(),
                                         'p90_spread_m': round(spread, 3),
                                         'body_translation_range_m': [round(v, 3) for v in rng],
                                         'verdict': verdict}
    return out


def contact_sheet(rows, cap, out_path, target, n=48):
    rs = [r for r in rows if r['target'] == target][:n]
    tiles = []
    for r in rs:
        im = cv2.imread(str(cap / r['image']))
        if r.get('ref') is not None:
            x1, y1, x2, y2 = map(int, r['ref'])
            cv2.rectangle(im, (x1, y1), (x2, y2), (255, 255, 255), 1)
        for c in r['candidates']:
            x1, y1, x2, y2 = map(int, c['box'])
            cv2.rectangle(im, (x1, y1), (x2, y2), (0, 255, 0) if c['accepted'] else (0, 0, 255), 2)
            cv2.putText(im, '%.2f %s' % (c['score'], c.get('reject', '')), (x1, max(12, y1 - 4)), 0, 0.5,
                        (0, 255, 0) if c['accepted'] else (0, 0, 255), 1)
        im = cv2.resize(im, (320, 240))
        cv2.putText(im, Path(r['image']).stem, (4, 234), 0, 0.4, (0, 255, 255), 1)
        tiles.append(im)
    if not tiles:
        return
    while len(tiles) % 6:
        tiles.append(np.zeros_like(tiles[0]))
    cv2.imwrite(str(out_path), np.vstack([np.hstack(tiles[i:i + 6]) for i in range(0, len(tiles), 6)]))


def images_only(a, sm, legacy, yolo):
    """Recognition-only evaluation on saved front frames (no odom/depth needed)."""
    paths = sorted(p for p in a.images.rglob('*') if p.suffix.lower() in ('.png', '.jpg', '.jpeg'))
    paths = paths[::a.stride][:a.max_per_camera]
    rows = []
    for path in paths:
        bgr = cv2.imread(str(path))
        if bgr is None or bgr.shape[:2] != (480, 640):
            continue
        for tgt in ('square_frame', 'pillar'):
            spec = TARGETS[tgt]
            t0 = time.monotonic()
            boxes = sm.propose(bgr, spec, path.name, a.method)
            probs = sm.verify(bgr, boxes, spec, path.name)
            cands = [{'box': [round(v, 1) for v in b], 'score': round(p, 3), 'accepted': True}
                     for b, p in select_candidates(spec, boxes, probs)]
            for b, p in zip(boxes, probs):
                if p < spec.verify_threshold:
                    cands.append({'box': [round(v, 1) for v in b], 'score': round(p, 3), 'accepted': False,
                                  'reject': 'verify'})
            ref = yolo(bgr) if tgt == 'square_frame' else None
            best = next((c for c in cands if c['accepted']), None)
            row = {'image': str(path.relative_to(a.images)), 'target': tgt, 'proposals': boxes, 'method': a.method, 'probs': probs,
                   'candidates': cands, 'latency_s': time.monotonic() - t0, 'accepted': best is not None,
                   'world': None, 'ref_known': tgt == 'square_frame', 'ref': ref}
            if best and ref:
                row['iou'] = geo.iou(best['box'], ref)
                row['center_err'] = float(np.hypot((best['box'][0] + best['box'][2] - ref[0] - ref[2]) / 2,
                                                   (best['box'][1] + best['box'][3] - ref[1] - ref[3]) / 2))
            if best and tgt == 'square_frame':   # what the depth gate would see, using size-depth only
                row['size_depth'] = geo.size_depth(best['box'], spec.width_m, spec.height_m)
            if legacy is not None and tgt == 'square_frame':
                lb, p0 = legacy_sweep_box(legacy, bgr)
                lrow = {'box': lb, 'p0': p0}
                if lb and ref:
                    lrow['iou'] = geo.iou(lb, ref)
                    lrow['size_ratio'] = (lb[2] - lb[0]) / max(1.0, ref[2] - ref[0])
                row['legacy'] = lrow
            rows.append(row)
            print(json.dumps({k: row.get(k) for k in ('image', 'target', 'accepted', 'iou', 'latency_s')},
                             default=float), flush=True)
    with (a.out / 'results.jsonl').open('w') as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, default=float) + '\n')
    summary = summarize(rows)
    summary['_mode'] = 'images_only: recognition + boxes; positions/depth gate NOT evaluated'
    (a.out / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=float))
    for tgt in ('square_frame', 'pillar'):
        contact_sheet(rows, a.images, a.out / ('sheet_%s.jpg' % tgt), tgt)
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=float))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--capture', type=Path, help='capture_scene.py output (images + odom + depth)')
    ap.add_argument('--images', type=Path, help='image-only mode: a folder of front-camera frames '
                    '(e.g. the 6.3 frame audit images/). Scores recognition + boxes only; no positions.')
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--model-dir', default='/home/ubuntu/model/FM9G4B-V')
    ap.add_argument('--workspace', default='/home/ubuntu/catkin_ws')
    ap.add_argument('--labels', type=Path, help='jsonl: {"image","target","box":[..]|null}')
    ap.add_argument('--stride', type=int, default=1)
    ap.add_argument('--max-per-camera', type=int, default=150)
    ap.add_argument('--legacy-sweep', action='store_true')
    ap.add_argument('--method', choices=('scan', 'native'), default='scan',
                    help="proposal method; 'native' = FM9G <box> (placeholder output on 2026-11-02 frames)")
    ap.add_argument('--simulate-balloon-processor', action='store_true',
                    help='set scale_resolution=224 first, as the balloon bridge does')
    a = ap.parse_args()
    if bool(a.capture) == bool(a.images):
        ap.error('give exactly one of --capture or --images')
    a.out.mkdir(parents=True, exist_ok=False)

    import torch
    model, tok, proc = load(a.model_dir)
    if a.simulate_balloon_processor and hasattr(proc, 'image_processor'):
        proc.image_processor.scale_resolution = 224
    from fm9g_scene.presence import FastPresence, NativePresenceSweep
    import threading
    lock = threading.Lock()
    log = (a.out / 'calls.jsonl').open('w', buffering=1)
    audit = lambda **e: log.write(json.dumps(e, ensure_ascii=False, default=float) + '\n')  # noqa: E731
    fp = FastPresence(model, tok, proc, res=224)
    sm = SceneModel(model, tok, proc, lock, audit, fp)
    legacy = (NativePresenceSweep(model, tok, proc, lock, audit, lambda e: True, res=224, n_initial=8)
              if a.legacy_sweep else None)
    try:
        yolo = YoloRef(a.workspace)
    except Exception as exc:          # reference only; evaluation still runs without it
        print('YOLO reference unavailable (%r); square_frame scored by contact sheet only' % exc, flush=True)
        yolo = lambda bgr: None       # noqa: E731
    labels = {}
    if a.labels:
        for line in a.labels.open():
            l = json.loads(line)
            labels[(l['image'], l['target'])] = l['box']

    if a.images:
        return images_only(a, sm, legacy, yolo)
    frames = [json.loads(l) for l in (a.capture / 'index.jsonl').open() if '"frame"' in l]
    rows = []
    for cam in ('front', 'down'):
        sel = [f for f in frames if f['camera'] == cam][::a.stride][:a.max_per_camera]
        for f in sel:
            bgr = cv2.imread(str(a.capture / f['image']))
            pos, R = np.array(f['pos']), geo.quat_to_R(*f['quat'])
            cloud = (np.load(a.capture / f['cloud'])['xyz'].astype(float) if f.get('cloud') else None)
            for tgt in CAMERA_TARGETS[cam]:
                spec = TARGETS[tgt]
                t0 = time.monotonic()
                boxes = sm.propose(bgr, spec, f['image'], a.method)
                probs = sm.verify(bgr, boxes, spec, f['image'])
                cands = [localise(spec, b, p, pos, R, cloud) for b, p in select_candidates(spec, boxes, probs)]
                latency = time.monotonic() - t0
                ref_known, ref = False, None
                if tgt == 'square_frame':
                    ref_known, ref = True, yolo(bgr)
                elif tgt == 'aruco_marker':
                    ref_known, ref = True, aruco_ref(bgr)
                elif (f['image'], tgt) in labels:
                    ref_known, ref = True, labels[(f['image'], tgt)]
                best = next((c for c in cands if c['accepted']), None)
                row = {'image': f['image'], 'target': tgt, 'stamp': f['stamp'], 'pos': f['pos'],
                       'proposals': boxes, 'method': a.method, 'probs': probs, 'candidates': cands, 'latency_s': latency,
                       'accepted': best is not None, 'world': best['world'] if best else None,
                       'ref_known': ref_known, 'ref': ref}
                if best and ref:
                    row['iou'] = geo.iou(best['box'], ref)
                    row['center_err'] = float(np.hypot((best['box'][0] + best['box'][2] - ref[0] - ref[2]) / 2,
                                                       (best['box'][1] + best['box'][3] - ref[1] - ref[3]) / 2))
                if ref:   # where the reference box would put the target (same gates)
                    rr = localise(spec, ref, 1.0, pos, R, cloud)
                    row['ref_world'] = rr.get('world')
                    row['yaw'] = float(np.arctan2(R[1, 0], R[0, 0]))
                if legacy is not None and tgt == 'square_frame':
                    lb, p0 = legacy_sweep_box(legacy, bgr)
                    lrow = {'box': lb, 'p0': p0}
                    if lb and ref:
                        lrow['iou'] = geo.iou(lb, ref)
                        lrow['size_ratio'] = (lb[2] - lb[0]) / max(1.0, ref[2] - ref[0])
                    row['legacy'] = lrow
                rows.append(row)
                print(json.dumps({k: row.get(k) for k in ('image', 'target', 'accepted', 'iou', 'world', 'latency_s')},
                                 default=float), flush=True)
            torch.cuda.empty_cache()

    with (a.out / 'results.jsonl').open('w') as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, default=float) + '\n')
    summary = summarize(rows)
    (a.out / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=float))
    for tgt in TARGETS:
        contact_sheet(rows, a.capture, a.out / ('sheet_%s.jpg' % tgt), tgt)
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=float))


if __name__ == '__main__':
    main()
