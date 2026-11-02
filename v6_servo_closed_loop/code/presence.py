"""FM9G4B-V native presence and four-direction sweep used by the flight bridge.

This module deliberately contains no detector, colour threshold, simulator
truth, or ROS dependency.  It asks the single FM9G4B-V instance only whether
the requested colour is present in each tile or masked crop.
"""
import math
import time

import numpy as np
import torch
import torch.nn.functional as F


class FastPresence:
    def __init__(self, model, tok, proc, res=224):
        assert res % 14 == 0 and res <= 448
        self.model, self.tok, self.proc, self.res = model, tok, proc, res
        self.yes = tok.encode("是", add_special_tokens=False)[-1]
        self.no = tok.encode("否", add_special_tokens=False)[-1]
        self._tmpl = {}
        from PIL import Image
        self._dummy = Image.new("RGB", (res, res))

    def template(self, text):
        if text not in self._tmpl:
            p = self.proc.tokenizer.apply_chat_template(
                [{"role": "user", "content": "(<image>./</image>)\n" + text}],
                tokenize=False, add_generation_prompt=True)
            inp = self.proc([p], [[self._dummy]], max_slice_nums=1,
                            return_tensors="pt", max_length=8192)
            if len(inp["pixel_values"][0]) != 1:
                raise ValueError("presence template must contain one slice")
            self._tmpl[text] = (inp["input_ids"][0], inp["image_bound"][0],
                                inp["tgt_sizes"][0])
        return self._tmpl[text]

    def pixels(self, rgb_u8):
        x = rgb_u8.permute(0, 3, 1, 2).float()
        if x.shape[-1] != self.res or x.shape[-2] != self.res:
            x = F.interpolate(x, size=(self.res, self.res), mode="bicubic",
                              align_corners=False).clamp(0, 255)
        x = (x / 255.0 - 0.5) / 0.5
        p = 14
        u = F.unfold(x, (p, p), stride=(p, p))
        batch, _, length = u.shape
        return u.reshape(batch, 3, p, p, length).permute(
            0, 1, 2, 4, 3).reshape(batch, 3, p, length * p)

    @torch.inference_mode()
    def __call__(self, rgb_u8, texts):
        if isinstance(texts, str):
            texts = [texts] * rgb_u8.shape[0]
        device = self.model.device
        pix = self.pixels(rgb_u8).to(torch.bfloat16)
        ids, bounds, _ = zip(*[self.template(t) for t in texts])
        length = max(len(i) for i in ids)
        input_ids = torch.zeros(len(ids), length, dtype=torch.long)
        attention = torch.zeros(len(ids), length, dtype=torch.bool)
        image_bound = []
        for k, (i, bound) in enumerate(zip(ids, bounds)):
            pad = length - len(i)
            input_ids[k, pad:] = i
            attention[k, pad:] = True
            image_bound.append(bound + pad)
        grid = self.res // 14
        target = torch.tensor([[grid, grid]], dtype=torch.int32, device=device)
        data = {
            "input_ids": input_ids.to(device),
            "image_bound": [b.to(device) for b in image_bound],
            "pixel_values": [[pix[k]] for k in range(len(ids))],
            "tgt_sizes": [target for _ in ids],
        }
        embeddings, _ = self.model.get_vllm_embedding(data)
        attention = attention.to(device)
        positions = (attention.long().cumsum(-1) - 1).clamp(min=0)
        logits = self.model.llm(
            inputs_embeds=embeddings,
            attention_mask=attention,
            position_ids=positions,
        ).logits[:, -1].float()
        return torch.softmax(torch.stack([logits[:, self.yes], logits[:, self.no]], -1), -1)[:, 0].tolist()


class NativePresenceSweep:
    """P12e acquisition/track sweep with structured model-call auditing."""
    def __init__(self, model, tokenizer, processor, model_lock, audit, active,
                 res=224, n_initial=8, n_track=7, window_factor=2.2,
                 thresholds=(0.4, 0.5, 0.5, 0.4)):
        self.model_lock = model_lock
        self.audit = audit
        self.active = active
        self.res = res
        self.n_initial = n_initial
        self.n_track = n_track
        self.window_factor = window_factor
        self.thresholds = tuple(float(v) for v in thresholds)
        # A window the balloon overflows cannot be measured (every masked
        # probe still sees it), so retry with a larger one before giving up.
        self.grow_factors = (1.0, 1.7, 2.6)
        self.fp = FastPresence(model, tokenizer, processor, res=res)

    def warmup(self, text='这张图片里有没有红色的气球？只回答“是”或“否”。'):
        """Build the processor template and GPU kernels before the first frame."""
        dummy = torch.zeros(41, self.res, self.res, 3,
                            dtype=torch.uint8, device='cuda')
        start = time.monotonic()
        with self.model_lock, torch.inference_mode():
            for _ in range(3):
                self.fp(dummy, text)
        self.audit(kind='presence_warmup', batch_size=41,
                   image_count=41, latency_s=time.monotonic()-start,
                   resolution=self.res)

    @staticmethod
    def square(cx, cy, side, width=640, height=480):
        size = int(min(max(side, 32), height))
        x = int(round(min(max(cx - size / 2, 0), width - size)))
        y = int(round(min(max(cy - size / 2, 0), height - size)))
        return x, y, x + size, y + size

    def crops(self, frame_bgr, windows):
        rgb = torch.from_numpy(frame_bgr[:, :, ::-1].copy()).cuda()
        out = []
        for x1, y1, x2, y2 in windows:
            crop = rgb[y1:y2, x1:x2].permute(2, 0, 1)[None].float()
            crop = F.interpolate(crop, size=(self.res, self.res), mode="bilinear",
                                 align_corners=False)[0].permute(1, 2, 0)
            out.append(crop.round().clamp(0, 255).byte())
        return torch.stack(out)

    def sweep_imgs(self, frame_bgr, window, count):
        gray = 128
        crop = self.crops(frame_bgr, [window])[0]
        side = window[2] - window[0]
        positions = list(np.linspace(0, side, count + 2)[1:-1])
        output = [crop]
        for direction in "LRTB":
            for distance in positions:
                masked = crop.clone()
                q = int(round(distance * self.res / side))
                if direction == "L": masked[:, :q] = gray
                if direction == "R": masked[:, self.res - q:] = gray
                if direction == "T": masked[:q, :] = gray
                if direction == "B": masked[self.res - q:, :] = gray
                output.append(masked)
        return torch.stack(output), positions

    @staticmethod
    def edge_box(probabilities, positions, window, thresholds):
        side = window[2] - window[0]
        count = len(positions)
        p0 = float(probabilities[0])
        crossings = []
        curves = []
        for direction in range(4):
            profile = [p0] + list(probabilities[1 + direction * count:1 + (direction + 1) * count])
            xs = [0.0] + positions
            threshold = thresholds[direction] * p0
            value = float(side)
            for j in range(1, len(profile)):
                if profile[j - 1] >= threshold > profile[j]:
                    fraction = (profile[j - 1] - threshold) / (profile[j - 1] - profile[j] + 1e-9)
                    value = xs[j - 1] + fraction * (xs[j] - xs[j - 1])
                    break
            crossings.append(value)
            curves.append(profile)
        left, right, top, bottom = crossings
        box = [window[0] + side - right, window[1] + side - bottom,
               window[0] + left, window[1] + top]
        valid = p0 >= 0.5 and box[2] > box[0] + 2 and box[3] > box[1] + 2
        return (box if valid else None), p0, curves

    def call(self, images, text, epoch, decision, session, color, frame_seq,
             stamp, stage, windows=None):
        if not self.active(epoch):
            raise RuntimeError("presence inference became inactive")
        start = time.monotonic()
        with self.model_lock, torch.inference_mode():
            if not self.active(epoch):
                raise RuntimeError("presence inference became inactive")
            probabilities = self.fp(images, text)
        latency = time.monotonic() - start
        self.audit(kind="presence_model_call", decision=decision,
                   session=session, color=color, stage=stage,
                   batch_size=len(probabilities), image_count=len(images),
                   frame_seq=frame_seq, source_stamp=stamp,
                   latency_s=latency, probabilities=probabilities,
                   p0=float(probabilities[0]) if probabilities else None,
                   windows=windows or [])
        return probabilities

    def acquire(self, frame_bgr, text, epoch, decision, session, color,
                frame_seq, stamp):
        tile = 224
        xs = np.linspace(0, 640 - tile, 5).astype(int)
        ys = np.linspace(0, 480 - tile, 3).astype(int)
        windows = [(int(x), int(y), int(x) + tile, int(y) + tile)
                   for y in ys for x in xs]
        probabilities = self.call(self.crops(frame_bgr, windows), text, epoch,
                                  decision, session, color, frame_seq, stamp,
                                  "acquire_tiles", windows)
        positive = [w for w, p in zip(windows, probabilities) if p >= 0.5]
        if not positive:
            return None
        best = windows[int(np.argmax(probabilities))]
        group = [w for w in positive
                 if min(w[2], best[2]) > max(w[0], best[0]) and
                 min(w[3], best[3]) > max(w[1], best[1])]
        roi = (max(w[0] for w in group), max(w[1] for w in group),
               min(w[2] for w in group), min(w[3] for w in group))
        if roi[2] - roi[0] < 48 or roi[3] - roi[1] < 48:
            roi = best
        for window in (
            self.square((roi[0] + roi[2]) / 2, (roi[1] + roi[3]) / 2,
                        max(roi[2] - roi[0], roi[3] - roi[1], 128)),
            tuple(best),
        ):
            images, positions = self.sweep_imgs(frame_bgr, window, self.n_initial)
            probabilities = self.call(images, text, epoch, decision, session,
                                      color, frame_seq, stamp, "acquire_sweep",
                                      [window])
            box, p0, curves = self.edge_box(probabilities, positions, window,
                                             (0.5,) * 4)
            self.audit(kind="presence_sweep", decision=decision, session=session,
                       color=color, stage="acquire_sweep", frame_seq=frame_seq,
                       p0=p0, curves=curves, thresholds=(0.5,) * 4,
                       box=box, window=window, positions=positions)
            if box:
                return box
        return None

    def track(self, frame_bgr, text, previous_box, epoch, decision, session,
              color, frame_seq, stamp, center=None, side=None, max_growth=1.25):
        cx = (previous_box[0] + previous_box[2]) / 2 if center is None else center[0]
        cy = (previous_box[1] + previous_box[3]) / 2 if center is None else center[1]
        if side is None:
            side = max(56, self.window_factor * max(previous_box[2] - previous_box[0],
                                                    previous_box[3] - previous_box[1]))
        candidate = None
        fallback = None
        for attempt, factor in enumerate(self.grow_factors):
            window = self.square(cx, cy, side * factor)
            count = self.n_track if attempt == 0 else max(4, self.n_track - 3)
            images, positions = self.sweep_imgs(frame_bgr, window, count)
            probabilities = self.call(images, text, epoch, decision, session,
                                      color, frame_seq, stamp, "track_sweep",
                                      [window])
            box, p0, curves = self.edge_box(probabilities, positions, window,
                                            self.thresholds)
            c = []
            # The sweep profile contains the unmasked crop at coordinate 0.0,
            # followed by samples at `positions`.  Keep that origin in the
            # interpolation grid: indexing `positions` directly shifts every
            # crossing by one sample interval and raises IndexError when the
            # crossing is in the final interval.
            xs = [0.0] + positions
            for profile, threshold in zip(curves, self.thresholds):
                value = None
                for j in range(1, len(profile)):
                    if profile[j - 1] >= threshold * p0 > profile[j]:
                        fraction = (profile[j - 1] - threshold * p0) / (profile[j - 1] - profile[j] + 1e-9)
                        value = xs[j - 1] + fraction * (xs[j] - xs[j - 1])
                        break
                c.append(value)
            saturated = [value is None for value in c]
            self.audit(kind="presence_sweep", decision=decision, session=session,
                       color=color, stage="track_sweep", frame_seq=frame_seq,
                       p0=p0, curves=curves, thresholds=self.thresholds,
                       box=box, window=window, positions=positions,
                       attempt=attempt, crossings=c, saturated=saturated)
            if p0 < 0.5:
                return None
            side_px = window[2] - window[0]
            window_box = [float(window[0]), float(window[1]),
                          float(window[2]), float(window[3])]
            if any(saturated):
                # The balloon runs past this window on some side: no honest box
                # exists, widen and try again.
                fallback = window_box
                continue
            left, right, top, bottom = c
            box = [window[0] + side_px - right, window[1] + side_px - bottom,
                   window[0] + left, window[1] + top]
            if box[2] <= box[0] + 2 or box[3] <= box[1] + 2:
                fallback = window_box
                continue
            candidate = box
            break
        if candidate is None:
            candidate = fallback if fallback is not None else list(previous_box)
        old_w, old_h = previous_box[2] - previous_box[0], previous_box[3] - previous_box[1]
        width = min(max(candidate[2] - candidate[0], 0.85 * old_w), max_growth * old_w)
        height = min(max(candidate[3] - candidate[1], 0.85 * old_h), max_growth * old_h)
        cx = (candidate[0] + candidate[2]) / 2
        cy = (candidate[1] + candidate[3]) / 2
        width, height = max(width, 12.0), max(height, 12.0)
        if height < 0.6 * width:
            cy, height = cy - (0.6 * width - height) / 2, 0.6 * width
        if height > 1.8 * width:
            width = height / 1.8
        width = min(width, 640.0)
        height = min(height, 480.0)
        cx = min(max(cx, width / 2), 640.0 - width / 2)
        cy = min(max(cy, height / 2), 480.0 - height / 2)
        return [cx - width / 2, cy - height / 2,
                cx + width / 2, cy + height / 2]
