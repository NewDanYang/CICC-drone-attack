"""Select a real C++17 compiler for deployed-source regression harnesses."""
import os
from pathlib import Path
import shutil


def compiler_command(root):
    requested = os.environ.get("CXX")
    if requested:
        return [requested, "c++"] if Path(requested).stem.lower() == "zig" else [requested]
    zig = Path(root) / ".local-toolchain/zig-windows-x86_64-0.13.0/zig.exe"
    if zig.is_file():
        return [str(zig), "c++"]
    compiler = shutil.which("g++") or shutil.which("clang++") or shutil.which("c++")
    return [compiler] if compiler else None
