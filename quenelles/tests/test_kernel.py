import os

import pytest
from kernel_driver import KernelDriver


@pytest.mark.asyncio
async def test_kernel(capfd):
    timeout = 1
    kernelspec_path = (
        os.environ["CONDA_PREFIX"] + "/share/jupyter/kernels/quenelles/kernel.json"
    )
    connection_file = "connection_file.json"
    kd = KernelDriver(
        kernelspec_path=kernelspec_path,
        connection_file=connection_file,
        capture_kernel_output=False,
        log=False,
    )
    try:
        await kd.start(timeout)
        await kd.execute("print('Hello World!')", timeout)
    except RuntimeError:
        pass
    finally:
        await kd.stop()

    out, err = capfd.readouterr()
    assert out == "Hello World!\n"
