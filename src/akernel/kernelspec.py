from __future__ import annotations

import json
import sys
from pathlib import Path


def write_kernelspec(dir_name: str, display_name: str, execute_in_thread: bool = False) -> None:
    argv = ["akernel", "launch"]
    if execute_in_thread:
        argv.append("--execute-in-thread")
    argv += ["-f", "{connection_file}"]
    kernelspec = {
        "argv": argv,
        "display_name": display_name,
        "language": "python",
    }
    directory = Path(sys.prefix) / "share" / "jupyter" / "kernels" / dir_name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "kernel.json").write_text(json.dumps(kernelspec, indent=2), encoding="utf-8")
