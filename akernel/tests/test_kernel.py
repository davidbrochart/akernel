import os
import asyncio

import pytest
from kernel_driver import KernelDriver


@pytest.mark.asyncio
async def test_kernel(capfd):
    timeout = 1
    kernelspec_path = (
        os.environ["CONDA_PREFIX"] + "/share/jupyter/kernels/akernel/kernel.json"
    )
    kd = KernelDriver(kernelspec_path=kernelspec_path, log=False)
    await kd.start(startup_timeout=timeout)
    await kd.execute("print('Hello World!')", timeout=timeout)
    await kd.execute("a = 1", timeout=timeout)
    await kd.execute("print(a)", timeout=timeout)
    await kd.execute("a += 2", timeout=timeout)
    await kd.execute("print(a)", timeout=timeout)
    asyncio.create_task(
        kd.execute("await asyncio.sleep(0.1)\nprint('done1')", timeout=timeout)
    )
    asyncio.create_task(
        kd.execute("await asyncio.sleep(0.2)\nprint('done2')", timeout=timeout)
    )
    await asyncio.sleep(0.3)
    await kd.stop()

    out, err = capfd.readouterr()
    assert out == "Hello World!\n1\n3\ndone1\ndone2\n"
