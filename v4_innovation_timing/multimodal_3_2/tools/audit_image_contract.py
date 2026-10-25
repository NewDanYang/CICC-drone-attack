"""Trace the installed model's real chat preprocessor without model/GPU/ROS.

Usage: python audit_image_contract.py --model-source /path/modeling_fm9gv.py
Only the chat method's AST is executed, and a processor spy stops execution
before tensors or inference are reached. This is an input-contract audit,
not a visual performance test. The image is a marker solely for counting.
"""
import argparse
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace


class StopBeforeInference(Exception):
    pass


class ProcessorSpy:
    def __init__(self):
        self.image_processor = SimpleNamespace(
            image_feature_size=64, patch_size=14, use_image_id=True,
            max_slice_nums=9, slice_mode=True)
        self.tokenizer = SimpleNamespace(apply_chat_template=lambda *a, **k: 'unused')
        self.counts = None

    def __call__(self, prompts, images, **kwargs):
        self.counts = [len(batch) for batch in images]
        raise StopBeforeInference


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-source', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    model_raw = args.model_source.read_bytes()
    method = next(n for n in ast.walk(ast.parse(model_raw))
                  if isinstance(n, ast.FunctionDef) and n.name == 'chat')
    method.decorator_list = []
    # The installed chat checks Image.Image. No real image analysis is done.
    class MarkerImage:
        pass
    namespace = dict(deepcopy=deepcopy, json=json,
                     Image=SimpleNamespace(Image=MarkerImage))
    module = ast.Module(body=[method], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(args.model_source), 'exec'), namespace)

    tested = Path(__file__).parents[1] / 'staging' / 'mission_once.py'
    tested_raw = tested.read_bytes()
    parsed = ast.parse(tested_raw)
    # Extract the actual tested kwargs construction, not a handwritten replica.
    constructor = next(n for n in ast.walk(parsed)
                       if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                       and n.func.id == 'dict'
                       and {'image', 'msgs', 'tokenizer'} <= {k.arg for k in n.keywords})
    kwargs = eval(compile(ast.Expression(constructor), str(tested), 'eval'),
                  dict(image=MarkerImage(), MULTIMODAL_PROMPT='input-contract marker',
                       self=SimpleNamespace(tokenizer=None)))
    cases = {
        'tested_list_text_only': kwargs,
        'string_content_with_image_kwarg': dict(kwargs, msgs=[{'role':'user', 'content':'marker'}]),
        'explicit_image_in_content': dict(kwargs, image=None,
            msgs=[{'role':'user', 'content':[MarkerImage(), 'marker']}]),
    }
    counts = {}
    for label, call_kwargs in cases.items():
        processor = ProcessorSpy()
        config = SimpleNamespace(query_num=64, patch_size=14, use_image_id=True,
            slice_config=SimpleNamespace(max_slice_nums=9), slice_mode=True)
        model = SimpleNamespace(config=config, processor=processor, device='cpu')
        try:
            namespace['chat'](model, processor=processor, **call_kwargs)
        except StopBeforeInference:
            counts[label] = processor.counts
        else:
            raise AssertionError('processor spy was not called')
    assert counts == {'tested_list_text_only':[0],
                      'string_content_with_image_kwarg':[1],
                      'explicit_image_in_content':[1]}, counts
    result = dict(scope='AST processor-spy contract audit; no model inference',
                  model_source_md5=hashlib.md5(model_raw).hexdigest(),
                  model_source_sha256=hashlib.sha256(model_raw).hexdigest(),
                  tested_candidate_md5=hashlib.md5(tested_raw).hexdigest(),
                  images_delivered_to_processor=counts)
    output = json.dumps(result, indent=2, ensure_ascii=False) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding='utf-8')
    print(output, end='')


if __name__ == '__main__':
    main()
