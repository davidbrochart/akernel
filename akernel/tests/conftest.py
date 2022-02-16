import pytest

from akernel.kernelspec import write_kernelspec


@pytest.fixture(scope="function", params=["", "multi", "react", "cache"])
def all_modes(request):
    mode = request.param
    kernel_name = "akernel"
    if mode:
        kernel_name += f"-{mode}"
    display_name = f"Python 3 ({kernel_name})"
    write_kernelspec("akernel", mode, display_name)
