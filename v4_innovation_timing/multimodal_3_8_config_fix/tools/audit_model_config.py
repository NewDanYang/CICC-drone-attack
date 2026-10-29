#!/usr/bin/env python3
"""Audit tokenizer formats, module names, and the effective PEFT surface."""
import argparse
import json
import re
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--adapter-config", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    import torch
    from transformers import AutoConfig, AutoModel, AutoTokenizer

    model_path = Path(args.model)
    tok = AutoTokenizer.from_pretrained(
        str(model_path), trust_remote_code=True, local_files_only=True
    )
    vocab = tok.get_vocab()
    candidates = ["<box>", "</box>", "<ref>", "</ref>", "<point>", "</point>",
                  "<quad>", "</quad>", "<bbox>", "</bbox>"]
    token_inventory = {
        "vocab_size": len(vocab),
        "candidate_presence": {x: x in vocab for x in candidates},
        "candidate_ids": {x: vocab.get(x) for x in candidates},
        "special_tokens_map": tok.special_tokens_map,
        "all_special_tokens": tok.all_special_tokens,
        "added_vocab": tok.get_added_vocab(),
    }

    examples = {
        "box": "<box>123 456 789 900</box>",
        "json": '{"bbox":[123,456,789,900]}',
        "brackets": "[123, 456, 789, 900]",
    }
    tokenization = {}
    for name, text in examples.items():
        ids = tok.encode(text, add_special_tokens=False)
        tokenization[name] = {
            "text": text,
            "ids": ids,
            "tokens": tok.convert_ids_to_tokens(ids),
            "count": len(ids),
        }

    config = AutoConfig.from_pretrained(
        str(model_path), trust_remote_code=True, local_files_only=True
    )
    # Load on CPU only for an exact named_modules() audit. No training or GPU use.
    model = AutoModel.from_pretrained(
        str(model_path), trust_remote_code=True, local_files_only=True,
        torch_dtype=torch.bfloat16, low_cpu_mem_usage=True, device_map="cpu",
    )
    llm_attn = []
    llm_linear_suffixes = set()
    vpm_suffixes = set()
    resampler_suffixes = set()
    for name, module in model.named_modules():
        if "self_attn" in name and ("llm" in name or name.startswith("model")):
            llm_attn.append({"name": name, "class": module.__class__.__name__})
        if name.startswith("llm.") or name.startswith("model.llm."):
            if name.endswith(("q_proj", "k_proj", "v_proj", "o_proj", "q_a_proj",
                              "q_b_proj", "kv_a_proj", "kv_b_proj", "out_proj")):
                llm_linear_suffixes.add(name.split("self_attn.")[-1])
        if name.startswith("vpm."):
            vpm_suffixes.add(name.split("vpm.", 1)[1].split(".")[-1])
        if name.startswith("resampler."):
            resampler_suffixes.add(name.split("resampler.", 1)[1].split(".")[-1])

    adapter = json.loads(Path(args.adapter_config).read_text(encoding="utf-8"))
    report = {
        "model": str(model_path),
        "config_class": config.__class__.__name__,
        "architectures": getattr(config, "architectures", None),
        "tokenizer": token_inventory,
        "tokenization": tokenization,
        "llm_attention_modules_sample": llm_attn[:100],
        "llm_attention_module_count": len(llm_attn),
        "llm_linear_suffixes": sorted(llm_linear_suffixes),
        "vpm_suffixes": sorted(vpm_suffixes),
        "resampler_suffixes": sorted(resampler_suffixes),
        "previous_adapter_config": adapter,
        "audit_conclusions": {
            "native_box_token_present": bool(
                token_inventory["candidate_presence"]["<box>"]
                and token_inventory["candidate_presence"]["</box>"]
            ),
            "previous_target_regex": adapter.get("target_modules"),
            "previous_modules_to_save": adapter.get("modules_to_save"),
        },
    }
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "out": args.out,
        "native_box_token_present": report["audit_conclusions"]["native_box_token_present"],
        "llm_attention_module_count": len(llm_attn),
        "llm_linear_suffixes": sorted(llm_linear_suffixes),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
