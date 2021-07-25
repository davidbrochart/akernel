import os
import asyncio
import signal
from textwrap import dedent

import pytest
from kernel_driver import KernelDriver  # type: ignore


TIMEOUT = 1
KERNELSPEC_PATH = (
    os.environ["CONDA_PREFIX"] + "/share/jupyter/kernels/akernel/kernel.json"
)


@pytest.mark.asyncio
async def test_syntax_error(capfd):
    kd = KernelDriver(kernelspec_path=KERNELSPEC_PATH, log=False)
    await kd.start(startup_timeout=TIMEOUT)
    await kd.execute("foo bar", timeout=TIMEOUT)
    await kd.stop()

    out, err = capfd.readouterr()
    assert err == dedent(
        """\
        File <string>, line 1:
        foo bar
            ^
        SyntaxError: invalid syntax
        """
    )


@pytest.mark.asyncio
async def test_name_not_defined(capfd):
    kd = KernelDriver(kernelspec_path=KERNELSPEC_PATH, log=False)
    await kd.start(startup_timeout=TIMEOUT)
    await kd.execute("foo", timeout=TIMEOUT)
    await kd.stop()

    out, err = capfd.readouterr()
    assert err == dedent(
        """\
        Traceback (most recent call last):
        <string> in <module> at line 1:
        foo
        NameError: name 'foo' is not defined
        """
    )


@pytest.mark.asyncio
async def test_hello_world(capfd):
    kd = KernelDriver(kernelspec_path=KERNELSPEC_PATH, log=False)
    await kd.start(startup_timeout=TIMEOUT)
    await kd.execute("print('Hello World!')", timeout=TIMEOUT)
    await kd.stop()

    out, err = capfd.readouterr()
    assert out == "Hello World!\n"


@pytest.mark.asyncio
async def test_global_variable(capfd):
    kd = KernelDriver(kernelspec_path=KERNELSPEC_PATH, log=False)
    await kd.start(startup_timeout=TIMEOUT)
    await kd.execute("a = 1", timeout=TIMEOUT)
    await kd.execute("print(a)", timeout=TIMEOUT)
    await kd.execute("a += 2", timeout=TIMEOUT)
    await kd.execute("print(a)", timeout=TIMEOUT)
    await kd.stop()

    out, err = capfd.readouterr()
    assert out == "1\n3\n"


@pytest.mark.asyncio
async def test_concurrent_cells(capfd):
    kd = KernelDriver(kernelspec_path=KERNELSPEC_PATH, log=False)
    await kd.start(startup_timeout=TIMEOUT)
    asyncio.create_task(
        kd.execute("await asyncio.sleep(0.2)\nprint('done1')", timeout=TIMEOUT)
    )
    asyncio.create_task(
        kd.execute("await asyncio.sleep(0.1)\nprint('done2')", timeout=TIMEOUT)
    )
    await asyncio.sleep(0.3)
    await kd.stop()

    out, err = capfd.readouterr()
    assert out == "done2\ndone1\n"


@pytest.mark.asyncio
async def test_chained_cells(capfd):
    kd = KernelDriver(kernelspec_path=KERNELSPEC_PATH, log=False)
    await kd.start(startup_timeout=TIMEOUT)
    asyncio.create_task(
        kd.execute("await asyncio.sleep(0.2)\nprint('done1')", timeout=TIMEOUT)
    )
    asyncio.create_task(
        kd.execute(
            "await __task__()\nawait asyncio.sleep(0.1)\nprint('done2')",
            timeout=TIMEOUT,
        )
    )
    await asyncio.sleep(0.4)
    await kd.stop()

    out, err = capfd.readouterr()
    assert out == "done1\ndone2\n"


@pytest.mark.asyncio
async def test_interrupt_async(capfd):
    kd = KernelDriver(kernelspec_path=KERNELSPEC_PATH, log=False)
    await kd.start(startup_timeout=TIMEOUT)
    expected = []
    n0, n1 = 2, 3
    for i0 in range(n0):
        for i1 in range(n1):
            asyncio.create_task(
                kd.execute(
                    f"print('{i0} {i1} before')\nawait asyncio.sleep(1)\nprint('{i0} {i1} after')",
                    timeout=TIMEOUT,
                )
            )
            expected.append(f"{i0} {i1} before")
        await asyncio.sleep(0.1)
        kd.kernel_process.send_signal(signal.SIGINT)
        await asyncio.sleep(0.1)
    await kd.stop()

    expected = "\n".join(expected) + "\n"
    out, err = capfd.readouterr()
    assert out == expected


@pytest.mark.asyncio
async def test_interrupt_chained(capfd):
    kd = KernelDriver(kernelspec_path=KERNELSPEC_PATH, log=False)
    await kd.start(startup_timeout=TIMEOUT)
    asyncio.create_task(
        kd.execute(
            "print('before 0')\nawait asyncio.sleep(1)\nprint('after 0')",
            timeout=TIMEOUT,
        )
    )
    asyncio.create_task(
        kd.execute(
            "await __task__()\nprint('before 1')\nawait asyncio.sleep(1)\nprint('after 1')",
            timeout=TIMEOUT,
        )
    )
    await asyncio.sleep(0.1)
    kd.kernel_process.send_signal(signal.SIGINT)
    await asyncio.sleep(0.1)
    await kd.stop()

    out, err = capfd.readouterr()
    assert out == "before 0\n"


@pytest.mark.asyncio
async def test_interrupt_blocking(capfd):
    kd = KernelDriver(kernelspec_path=KERNELSPEC_PATH, log=False)
    await kd.start(startup_timeout=TIMEOUT)
    asyncio.create_task(
        kd.execute(
            "import time\nprint('before 0')\ntime.sleep(1)\nprint('after 0')",
            timeout=TIMEOUT,
        )
    )
    asyncio.create_task(
        kd.execute(
            "print('before 1')\ntime.sleep(1)\nprint('after 1')", timeout=TIMEOUT
        )
    )
    await asyncio.sleep(0.1)
    kd.kernel_process.send_signal(signal.SIGINT)
    await asyncio.sleep(0.1)
    await kd.stop()

    out, err = capfd.readouterr()
    assert out == "before 0\n"


@pytest.mark.asyncio
async def test_repr(capfd):
    kd = KernelDriver(kernelspec_path=KERNELSPEC_PATH, log=False)
    await kd.start(startup_timeout=TIMEOUT)
    await kd.execute("1 + 2", timeout=TIMEOUT)
    await kd.stop()

    out, err = capfd.readouterr()
    assert out == "3\n"


@pytest.mark.asyncio
async def test_globals(capfd):
    code = dedent(
        """\
        a = 1
        def foo():
            global a
            a = 2
        foo()
        print(a)
        def bar():
            a = 3
        bar()
        print(a)
    """
    )
    kd = KernelDriver(kernelspec_path=KERNELSPEC_PATH, log=False)
    await kd.start(startup_timeout=TIMEOUT)
    await kd.execute(code, timeout=TIMEOUT)
    await kd.stop()

    out, err = capfd.readouterr()
    assert out == "2\n2\n"
