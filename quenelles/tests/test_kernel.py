import os

import pytest
from kernel_driver import KernelDriver


@pytest.mark.asyncio
async def test_kernel(capfd):
    timeout = 1
    kernelspec_path = (
        os.environ["CONDA_PREFIX"] + "/share/jupyter/kernels/quenelles/kernel.json"
    )
    kd = KernelDriver(kernelspec_path=kernelspec_path, log=False)
    await kd.start(timeout)
    await kd.execute("print('Hello World!')", timeout)
    await kd.stop()

    out, err = capfd.readouterr()
    assert out == "Hello World!\n"
