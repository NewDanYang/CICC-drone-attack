"""GPU fast path for FM9G4B-V single-slice presence scoring (P(是) vs P(否) from the first answer token).

Equivalent to processor(... max_slice_nums=1) for square inputs whose side is a multiple of 14 and <= 448
(no slicing happens there), but normalisation/patching/masking run on the GPU and the text template is built once.
"""
import torch
import torch.nn.functional as F


class FastPresence:
    def __init__(self, model, tok, proc, res=448):
        assert res % 14 == 0 and res <= 448
        self.model, self.tok, self.proc, self.res = model, tok, proc, res
        self.yes = tok.encode("是", add_special_tokens=False)[-1]
        self.no = tok.encode("否", add_special_tokens=False)[-1]
        self._tmpl = {}
        from PIL import Image
        self._dummy = Image.new("RGB", (res, res))

    def template(self, text):
        if text not in self._tmpl:
            p = self.proc.tokenizer.apply_chat_template([{"role": "user", "content": "(<image>./</image>)\n" + text}],
                                                        tokenize=False, add_generation_prompt=True)
            inp = self.proc([p], [[self._dummy]], max_slice_nums=1, return_tensors="pt", max_length=8192)
            assert len(inp["pixel_values"][0]) == 1, "template must contain exactly one slice"
            self._tmpl[text] = (inp["input_ids"][0], inp["image_bound"][0], inp["tgt_sizes"][0])
        return self._tmpl[text]

    def pixels(self, rgb_u8):
        """rgb_u8: uint8 tensor [B,H,W,3] on GPU (any H,W) -> list of [3,14,L] bf16 patches at self.res."""
        x = rgb_u8.permute(0, 3, 1, 2).float()
        if x.shape[-1] != self.res or x.shape[-2] != self.res:
            x = F.interpolate(x, size=(self.res, self.res), mode="bicubic", align_corners=False).clamp(0, 255)
        x = (x / 255.0 - 0.5) / 0.5
        p = 14
        u = F.unfold(x, (p, p), stride=(p, p))                       # [B, 3*p*p, L]
        B, _, L = u.shape
        u = u.reshape(B, 3, p, p, L).permute(0, 1, 2, 4, 3).reshape(B, 3, p, L * p)
        return u

    @torch.inference_mode()
    def __call__(self, rgb_u8, texts):
        """rgb_u8 [B,H,W,3] uint8 cuda; texts: str or list[str] (one template per item). Returns P(是) list."""
        if isinstance(texts, str):
            texts = [texts] * rgb_u8.shape[0]
        dev = self.model.device
        pix = self.pixels(rgb_u8).to(torch.bfloat16)
        ids, bounds, tgts = zip(*[self.template(t) for t in texts])
        Lmax = max(len(i) for i in ids)
        input_ids = torch.zeros(len(ids), Lmax, dtype=torch.long)
        am = torch.zeros(len(ids), Lmax, dtype=torch.bool)
        image_bound = []
        for k, (i, b) in enumerate(zip(ids, bounds)):
            pad = Lmax - len(i)
            input_ids[k, pad:] = i; am[k, pad:] = True; image_bound.append(b + pad)   # left padding, like the processor
        g = self.res // 14  # actual patch grid; the processor template was built for its own (upscaled) grid
        tgt = torch.tensor([[g, g]], dtype=torch.int32, device=dev)
        data = dict(input_ids=input_ids.to(dev), image_bound=[b.to(dev) for b in image_bound],
                    pixel_values=[[pix[k]] for k in range(len(ids))], tgt_sizes=[tgt for _ in ids])
        emb, _ = self.model.get_vllm_embedding(data)
        am = am.to(dev)
        pos = (am.long().cumsum(-1) - 1).clamp(min=0)
        lg = self.model.llm(inputs_embeds=emb, attention_mask=am, position_ids=pos).logits[:, -1].float()
        return torch.softmax(torch.stack([lg[:, self.yes], lg[:, self.no]], -1), -1)[:, 0].tolist()
