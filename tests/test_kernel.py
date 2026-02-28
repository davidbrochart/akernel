import os
import platform
import sys
import signal
import re
from functools import partial
from anyio import create_task_group, sleep
from pathlib import Path
from textwrap import dedent

import pytest
from kernel_driver import KernelDriver  # type: ignore


TIMEOUT = 5
KERNELSPEC_PATH = str(
    Path(sys.prefix) / "share" / "jupyter" / "kernels" / "akernel" / "kernel.json"
)


ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def interrupt_kernel(kernel_process):
    if platform.system() == "Windows":
        os.kill(kernel_process.pid, signal.CTRL_C_EVENT)
    else:
        kernel_process.send_signal(signal.SIGINT)


async def test_syntax_error(capfd):
    kd = KernelDriver(kernelspec_path=KERNELSPEC_PATH, log=False)
    await kd.start(startup_timeout=TIMEOUT)
    await kd.execute("foo bar", timeout=TIMEOUT)
    await kd.stop()

    out, err = capfd.readouterr()
    # ignore colors
    expected = dedent(
        """
        Cell 1, line 1:
        foo bar
        POINTER
        SyntaxError: invalid syntax
        """
    ).strip()
    if sys.version_info >= (3, 11):
        pointer = "    ^"
    elif sys.version_info >= (3, 10):
        pointer = "^"
        expected += ". Perhaps you forgot a comma?"
    elif sys.version_info >= (3, 8):
        pointer = "    ^"
    expected = expected.replace("POINTER", pointer)
    assert ANSI_ESCAPE.sub("", err).strip() == expected


async def test_name_not_defined(capfd):
    kd = KernelDriver(kernelspec_path=KERNELSPEC_PATH, log=False)
    await kd.start(startup_timeout=TIMEOUT)
    await kd.execute("foo", timeout=TIMEOUT)
    await kd.stop()

    out, err = capfd.readouterr()
    # ignore colors
    assert ANSI_ESCAPE.sub("", err) == dedent(
        """\
        Traceback (most recent call last):
        Cell 1 in <module>, line 1:
        foo
        NameError: name 'foo' is not defined
        """
    )


async def test_hello_world(capfd):
    kd = KernelDriver(kernelspec_path=KERNELSPEC_PATH, log=False)
    await kd.start(startup_timeout=TIMEOUT)
    await kd.execute("print('Hello World!')", timeout=TIMEOUT)
    await kd.stop()

    out, err = capfd.readouterr()
    assert out == "Hello World!\n"


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


async def test_concurrent_cells(capfd):
    async with create_task_group() as tg:
        kd = KernelDriver(kernelspec_path=KERNELSPEC_PATH, log=False)
        await kd.start(startup_timeout=TIMEOUT)
        tg.start_soon(partial(kd.execute, "__unchain_execution__()", timeout=TIMEOUT))
        tg.start_soon(partial(kd.execute, "from anyio import sleep", timeout=TIMEOUT))
        tg.start_soon(partial(kd.execute, "await sleep(0.2)\nprint('done1')", timeout=TIMEOUT))
        tg.start_soon(partial(kd.execute, "await sleep(0.1)\nprint('done2')", timeout=TIMEOUT))
        await sleep(0.5)
        await kd.stop()

    out, err = capfd.readouterr()
    assert out == "done2\ndone1\n"


async def test_chained_cells(capfd):
    async with create_task_group() as tg:
        kd = KernelDriver(kernelspec_path=KERNELSPEC_PATH, log=False)
        await kd.start(startup_timeout=TIMEOUT)
        tg.start_soon(partial(kd.execute, "from anyio import sleep", timeout=TIMEOUT))
        tg.start_soon(partial(kd.execute, "await sleep(0.2)\nprint('done1')", timeout=TIMEOUT))
        tg.start_soon(
            partial(
                kd.execute,
                "await __task__()\nawait sleep(0.1)\nprint('done2')",
                timeout=TIMEOUT,
            )
        )
        await sleep(1)
        await kd.stop()

        out, err = capfd.readouterr()
        assert out == "done1\ndone2\n"


async def test_interrupt_async(capfd):
    async with create_task_group() as tg:
        kd = KernelDriver(kernelspec_path=KERNELSPEC_PATH, log=False)
        await kd.start(startup_timeout=TIMEOUT)
        await kd.execute("__unchain_execution__()", timeout=TIMEOUT)
        expected = []
        n0, n1 = 2, 3
        for i0 in range(n0):
            for i1 in range(n1):
                tg.start_soon(
                    partial(
                        kd.execute,
                        f"from anyio import sleep\nprint('{i0} {i1} before')\nawait sleep(1)\nprint('{i0} {i1} after')",
                        timeout=TIMEOUT,
                    )
                )
                expected.append(f"{i0} {i1} before")
            await sleep(0.1)
            interrupt_kernel(kd.kernel_process)
            await sleep(0.1)
        await kd.stop()

        expected = "\n".join(expected) + "\n"
        out, err = capfd.readouterr()
        print(expected)
        assert out == expected


async def test_interrupt_chained(capfd):
    async with create_task_group() as tg:
        kd = KernelDriver(kernelspec_path=KERNELSPEC_PATH, log=False)
        await kd.start(startup_timeout=TIMEOUT)
        tg.start_soon(
            partial(
                kd.execute,
                "from anyio import sleep\nprint('before 0')\nawait sleep(1)\nprint('after 0')",
                timeout=TIMEOUT,
            )
        )
        tg.start_soon(
            partial(
                kd.execute,
                "await __task__()\nprint('before 1')\nawait sleep(1)\nprint('after 1')",
                timeout=TIMEOUT,
            )
        )
        await sleep(0.1)
        interrupt_kernel(kd.kernel_process)
        await sleep(0.1)
        await kd.stop()

        out, err = capfd.readouterr()
        assert out == "before 0\n"


async def test_interrupt_blocking(capfd):
    async with create_task_group() as tg:
        kd = KernelDriver(kernelspec_path=KERNELSPEC_PATH, log=False)
        await kd.start(startup_timeout=TIMEOUT)
        tg.start_soon(
            partial(
                kd.execute,
                "import time\nprint('before 0')\ntime.sleep(1)\nprint('after 0')",
                timeout=TIMEOUT,
            )
        )
        tg.start_soon(
            partial(
                kd.execute, "print('before 1')\ntime.sleep(1)\nprint('after 1')", timeout=TIMEOUT
            )
        )
        await sleep(0.1)
        interrupt_kernel(kd.kernel_process)
        await sleep(0.1)
        await kd.stop()

        out, err = capfd.readouterr()
        assert out == "before 0\n"


async def test_repr(capfd ):
    kd = KernelDriver(kernelspec_path=KERNELSPEC_PATH, log=False)
    await kd.start(startup_timeout=TIMEOUT)
    await kd.execute("1 + 2", timeout=TIMEOUT)
    await kd.stop()

    out, err = capfd.readouterr()
    assert out == "3\n"


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
