import os

import pytest
from kernel_driver import KernelDriver


@pytest.mark.asyncio
async def test_kernel(capfd):
    timeout = 1
    kernelspec_path = (
        os.environ["CONDA_PREFIX"] + "/share/jupyter/kernels/akernel/kernel.json"
    )
    kd = KernelDriver(kernelspec_path=kernelspec_path, log=False)
    await kd.start(timeout)
    await kd.execute("print('Hello World!')", timeout)
    await kd.execute("a = 1", timeout)
    await kd.execute("print(a)", timeout)
    await kd.execute("a += 2", timeout)
    await kd.execute("print(a)", timeout)
    await kd.execute("await asyncio.sleep(0.5)\nprint('done')", timeout)
    await kd.stop()

    out, err = capfd.readouterr()
    assert out == "Hello World!\n1\n3\ndone\n"
