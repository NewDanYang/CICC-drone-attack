"""Anchor-checked patch of /home/ubuntu/model/mission_once.py.

Two changes, nothing else:
  1. Command generation becomes deterministic: the two `sampling=True` chat
     calls (prompt injection in load_model, task -> command block in
     generate_commands) become `sampling=False`.  This targets the documented
     intermittent "好的，请描述您的任务需求。" reply (6.3 report: reproducible with a
     fixed sampling seed, i.e. a sampling outcome), instead of retrying it.
     Prompt text, parser and validation are untouched.
  2. `main()` is replaced by entry_main.py.txt, which builds the FM9G scene
     bridge (and, with FM9G_BALLOON_BRIDGE=1, the balloon bridge) on the same
     loaded model and lock.

Every other top-level function must be AST-identical apart from change 1;
the original EOL style (LF / CRLF / CRCRLF) and BOM are preserved.

Usage: python3 patch_mission_once.py <in> <out> [--keep-sampling]
"""
import ast
import hashlib
import sys
from pathlib import Path


def eol_of(data: bytes) -> bytes:
    for eol in (b'\r\r\n', b'\r\n'):
        if eol in data:
            return eol
    return b'\n'


def functions(text):
    return {n.name: ast.dump(n, include_attributes=False)
            for n in ast.parse(text).body if isinstance(n, ast.FunctionDef)}


def patch(data: bytes, template: str, greedy=True) -> bytes:
    bom = b'\xef\xbb\xbf' if data.startswith(b'\xef\xbb\xbf') else b''
    eol = eol_of(data)
    text = data[len(bom):].decode('utf-8').replace(eol.decode(), '\n')
    if text.count('def main():') != 1:
        raise SystemExit('main anchor count != 1')
    if 'fm9g_scene' in text:
        raise SystemExit('already patched')
    before = functions(text)
    for name in ('load_model', 'generate_commands', 'generate_validated_commands'):
        if name not in before:
            raise SystemExit('expected helper %s missing' % name)
    if greedy:
        if text.count('sampling=True') != 2:
            raise SystemExit('expected exactly 2 sampling=True, found %d' % text.count('sampling=True'))
        text = text.replace('sampling=True', 'sampling=False')
    head = text[:text.index('def main():')]
    result = head + template.replace('\r\n', '\n')
    after = functions(result)
    changed = sorted(n for n in before if n != 'main' and before[n] != after.get(n))
    allowed = {'load_model', 'generate_commands'} if greedy else set()
    if set(changed) - allowed:
        raise SystemExit('unexpected helper change: %s' % changed)
    compile(result, 'mission_once.py', 'exec')
    return bom + result.replace('\n', eol.decode()).encode('utf-8'), changed


if __name__ == '__main__':
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    greedy = '--keep-sampling' not in sys.argv
    template = (Path(__file__).with_name('entry_main.py.txt')).read_text(encoding='utf-8')
    raw = src.read_bytes()
    out, changed = patch(raw, template, greedy)
    with open(dst, 'xb') as f:
        f.write(out)
    print('in  md5', hashlib.md5(raw).hexdigest())
    print('out md5', hashlib.md5(out).hexdigest())
    print('helpers changed (sampling flag only):', changed)
