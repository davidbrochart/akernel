import pytest

from akernel.kernelspec import write_kernelspec


@pytest.fixture(scope="function", params=["async", "react"])
def all_modes(request):
    mode = request.param
    display_name = f"Python 3 (akernel-{mode})"
    write_kernelspec("akernel", mode, display_name)
