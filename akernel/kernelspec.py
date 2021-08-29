import os
import sys
import json


def write_kernelspec(dir_name: str, mode: str, display_name: str) -> None:
    kernelspec = {
        "argv": ["akernel", "launch", mode, "-f", "{connection_file}"],
        "display_name": display_name,
        "language": "python",
    }
    directory = os.path.join(sys.prefix, "share", "jupyter", "kernels", dir_name)
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, "kernel.json"), "wt") as f:
        json.dump(kernelspec, f, indent=2)
