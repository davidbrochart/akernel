import os
import shutil
import sys

import pytest

from akernel.kernelspec import write_kernelspec


@pytest.fixture(scope="function", params=["", "multi", "react", "cache"])
def all_modes(request):
    mode = request.param
    kernel_name = "akernel"
    if mode:
        kernel_name += f"-{mode}"
    if mode == "cache":
        cache_dir = os.path.join(
            sys.prefix, "share", "jupyter", "kernels", "akernel", "cache"
        )
        shutil.rmtree(cache_dir, ignore_errors=True)
    display_name = f"Python 3 ({kernel_name})"
    write_kernelspec("akernel", mode, display_name, None)
