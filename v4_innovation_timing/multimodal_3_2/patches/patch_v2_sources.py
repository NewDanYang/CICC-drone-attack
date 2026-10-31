"""Byte-preserving source transformation against the sealed deployed baseline."""
import argparse
import ast
import hashlib
from pathlib import Path


def patch_entry(source, template):
    if hashlib.md5(source).hexdigest() != 'fca24bf1142ca8cddfb9e8d39c387a43':
        raise ValueError('mission_once baseline MD5 mismatch')
    anchor=b'def main():'
    if source.count(anchor)!=1:
        raise ValueError('main anchor mismatch')
    result=source[:source.index(anchor)]+template.replace(b'\r\n',b'\n')
    before={n.name:ast.dump(n,include_attributes=False) for n in ast.parse(source).body if isinstance(n,ast.FunctionDef)}
    after={n.name:ast.dump(n,include_attributes=False) for n in ast.parse(result).body if isinstance(n,ast.FunctionDef)}
    if any(after.get(name)!=value for name,value in before.items() if name!='main'):
        raise ValueError('Command helper changed')
    return result


def patch_bt(source):
    if hashlib.md5(source).hexdigest() != '9b1cefe9dfa431418435f7f8f63a60ed':
        raise ValueError('bt_ros baseline MD5 mismatch')
    old=b'<TargetTracker object_name='
    if source.count(old)!=1:
        raise ValueError('Tracker anchor mismatch')
    result=source.replace(old,b'<MultimodalTargetTracker object_name=')
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('baseline',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    mission=patch_entry((args.baseline/'mission_once.py').read_bytes(),(root/'v2/entry_main.py.txt').read_bytes())
    bt=patch_bt((args.baseline/'bt_ros.cpp').read_bytes())
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'mission_once.py').write_bytes(mission)
    (args.output/'bt_ros.cpp').write_bytes(bt)
    print('mission_once',hashlib.md5(mission).hexdigest())
    print('bt_ros',hashlib.md5(bt).hexdigest())


if __name__=='__main__':
    main()
