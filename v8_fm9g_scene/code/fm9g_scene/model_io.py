"""FM9G4B-V calls used by the scene bridge: native box proposal + presence verify.

Shares the single loaded model (and its lock) with the balloon bridge; never
loads weights.  `FastPresence` is imported unchanged from the balloon package's
presence.py (copied next to this file at deploy time, MD5 recorded).
"""
import re
import time

import numpy as np

BOX_RE = re.compile(r'<box>\s*(\d{1,4})\s*[, ]\s*(\d{1,4})\s*[, ]\s*(\d{1,4})\s*[, ]\s*(\d{1,4})\s*</box>', re.I)
NONE_RE = re.compile(r'<box>\s*(?:none|null|无|不可见)?\s*</box>', re.I)


def parse_boxes(text):
    """All valid native boxes in a reply (0..1000 ints).  [] means 'none'."""
    out = []
    for m in BOX_RE.finditer(text or ''):
        x1, y1, x2, y2 = (int(v) for v in m.groups())
        if 0 <= x1 < x2 <= 1000 and 0 <= y1 < y2 <= 1000:
            out.append((x1, y1, x2, y2))
    return out


def expand(box, factor, width=640, height=480):
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    w, h = (box[2] - box[0]) * factor, (box[3] - box[1]) * factor
    return [max(0.0, cx - w / 2), max(0.0, cy - h / 2),
            min(float(width), cx + w / 2), min(float(height), cy + h / 2)]


class SceneModel:
    # The balloon bridge sets processor.image_processor.scale_resolution=224
    # process-wide for its own speed.  Native grounding at 224 px throws away
    # most of the detail, so every native call here sets the resolution it
    # needs and restores the previous value, all while holding model_lock.
    NATIVE_RESOLUTION = 448

    def __init__(self, model, tokenizer, processor, model_lock, audit, fast_presence):
        self.model, self.tok, self.proc = model, tokenizer, processor
        self.model_lock = model_lock
        self.audit = audit
        self.fp = fast_presence

    def native_boxes(self, bgr, spec, decision, max_new_tokens=96):
        from PIL import Image
        image = Image.fromarray(bgr[:, :, ::-1].copy())
        prompt = spec.ground_prompt()
        start = time.monotonic()
        ip = getattr(self.proc, 'image_processor', None)
        with self.model_lock:
            previous = getattr(ip, 'scale_resolution', None) if ip is not None else None
            try:
                if previous is not None:
                    ip.scale_resolution = self.NATIVE_RESOLUTION
                reply = self.model.chat(
                    image=None, msgs=[{'role': 'user', 'content': [image, prompt]}],
                    tokenizer=self.tok, processor=self.proc, sampling=False,
                    stream=False, max_new_tokens=max_new_tokens)
            finally:
                if previous is not None:
                    ip.scale_resolution = previous
        reply = reply if isinstance(reply, str) else ''.join(reply)
        boxes = parse_boxes(reply)
        self.audit(kind='native_call', decision=decision, target=spec.name,
                   latency_s=time.monotonic() - start, reply=reply[:300], boxes=boxes,
                   resolution=self.NATIVE_RESOLUTION)
        return boxes

    def verify(self, bgr, boxes_px, spec, decision, pad=1.15):
        """P(是) for the contrastive question on each (padded) box crop."""
        if not boxes_px:
            return []
        import torch
        import torch.nn.functional as F
        res = self.fp.res
        rgb = torch.from_numpy(bgr[:, :, ::-1].copy()).cuda()
        crops = []
        for box in boxes_px:
            x1, y1, x2, y2 = [int(round(v)) for v in expand(box, pad)]
            x2, y2 = max(x2, x1 + 2), max(y2, y1 + 2)
            c = rgb[y1:y2, x1:x2].permute(2, 0, 1)[None].float()
            c = F.interpolate(c, size=(res, res), mode='bilinear', align_corners=False)[0]
            crops.append(c.permute(1, 2, 0).round().clamp(0, 255).byte())
        start = time.monotonic()
        with self.model_lock:
            probs = self.fp(torch.stack(crops), spec.verify)
        self.audit(kind='verify_call', decision=decision, target=spec.name,
                   latency_s=time.monotonic() - start, probabilities=probs,
                   boxes=[list(map(float, b)) for b in boxes_px])
        return [float(p) for p in probs]

