import os
import sys
import json


def write_kernelspec(dir_name: str, mode: str, display_name: str) -> None:
    argv = ["akernel", "launch"]
    if mode:
        argv.append(mode)
    argv += ["-f", "{connection_file}"]
    kernelspec = {
        "argv": argv,
        "display_name": display_name,
        "language": "python",
    }
    directory = os.path.join(sys.prefix, "share", "jupyter", "kernels", dir_name)
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, "kernel.json"), "wt") as f:
        json.dump(kernelspec, f, indent=2)
