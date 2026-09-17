import json
import re
import sys
from functools import partial
from textwrap import dedent

import pytest
from anyio import create_task_group, sleep
from kernel_driver import KernelDriver  # type: ignore
from kernel_driver.driver import receive_message, send_message
from kernel_driver.message import create_message

TIMEOUT = 5


@pytest.fixture
def anyio_backend():
    # kernel_driver uses asyncio subprocesses and ZeroMQ sockets internally.
    return "asyncio"


@pytest.fixture
def kernelspec_path(tmp_path):
    # Launch this checkout without relying on an installed CLI entry point.
    path = tmp_path / "kernel.json"
    path.write_text(
        json.dumps(
            {
                "argv": [
                    sys.executable,
                    "-c",
                    "from akernel.akernel import app; app()",
                    "launch",
                    "-f",
                    "{connection_file}",
                ],
                "display_name": "akernel test",
                "language": "python",
            }
        )
    )
    return str(path)


ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


async def interrupt_kernel(driver):
    request = create_message("interrupt_request", session_id=driver.session_id)
    send_message(request, driver.control_channel, driver.key)
    reply = await receive_message(driver.control_channel, TIMEOUT)
    assert reply["msg_type"] == "interrupt_reply"


async def test_syntax_error(capfd, kernelspec_path):
    kd = KernelDriver(kernelspec_path=kernelspec_path, log=False)
    await kd.start(startup_timeout=TIMEOUT)
    await kd.execute("foo bar", timeout=TIMEOUT)
    await kd.stop()

    _out, err = capfd.readouterr()
    text = ANSI_ESCAPE.sub("", err)
    assert "SyntaxError: invalid syntax" in text
    assert "Cell 1, line 1" in text
    assert "foo bar" in text
    assert "▲" in text


async def test_name_not_defined(capfd, kernelspec_path):
    kd = KernelDriver(kernelspec_path=kernelspec_path, log=False)
    await kd.start(startup_timeout=TIMEOUT)
    await kd.execute("foo", timeout=TIMEOUT)
    await kd.stop()

    _out, err = capfd.readouterr()
    text = ANSI_ESCAPE.sub("", err)
    assert "Cell 1 (<module>):1" in text
    assert "NameError: name 'foo' is not defined" in text


async def test_hello_world(capfd, kernelspec_path):
    kd = KernelDriver(kernelspec_path=kernelspec_path, log=False)
    await kd.start(startup_timeout=TIMEOUT)
    await kd.execute("print('Hello World!')", timeout=TIMEOUT)
    await kd.stop()

    out, _err = capfd.readouterr()
    assert out == "Hello World!\n"


async def test_global_variable(capfd, kernelspec_path):
    kd = KernelDriver(kernelspec_path=kernelspec_path, log=False)
    await kd.start(startup_timeout=TIMEOUT)
    await kd.execute("a = 1", timeout=TIMEOUT)
    await kd.execute("print(a)", timeout=TIMEOUT)
    await kd.execute("a += 2", timeout=TIMEOUT)
    await kd.execute("print(a)", timeout=TIMEOUT)
    await kd.stop()

    out, _err = capfd.readouterr()
    assert out == "1\n3\n"


async def test_chained_cells(capfd, kernelspec_path):
    async with create_task_group() as tg:
        kd = KernelDriver(kernelspec_path=kernelspec_path, log=False)
        await kd.start(startup_timeout=TIMEOUT)
        tg.start_soon(partial(kd.execute, "from anyio import sleep", timeout=TIMEOUT))
        tg.start_soon(partial(kd.execute, "await sleep(0.2)\nprint('done1')", timeout=TIMEOUT))
        tg.start_soon(
            partial(
                kd.execute,
                "await sleep(0.1)\nprint('done2')",
                timeout=TIMEOUT,
            )
        )
        await sleep(1)
        await kd.stop()

        out, _err = capfd.readouterr()
        assert out == "done1\ndone2\n"


async def test_interrupt_chained(capfd, kernelspec_path):
    async with create_task_group() as tg:
        kd = KernelDriver(kernelspec_path=kernelspec_path, log=False)
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
                "print('before 1')\nawait sleep(1)\nprint('after 1')",
                timeout=TIMEOUT,
            )
        )
        await sleep(0.1)
        await interrupt_kernel(kd)
        await sleep(0.1)
        await kd.stop()

        out, _err = capfd.readouterr()
        assert out == "before 0\n"


async def test_repr(capfd, kernelspec_path):
    kd = KernelDriver(kernelspec_path=kernelspec_path, log=False)
    await kd.start(startup_timeout=TIMEOUT)
    await kd.execute("1 + 2", timeout=TIMEOUT)
    await kd.stop()

    out, _err = capfd.readouterr()
    assert out == "3\n"


async def test_globals(capfd, kernelspec_path):
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
    kd = KernelDriver(kernelspec_path=kernelspec_path, log=False)
    await kd.start(startup_timeout=TIMEOUT)
    await kd.execute(code, timeout=TIMEOUT)
    await kd.stop()

    out, _err = capfd.readouterr()
    assert out == "2\n2\n"
