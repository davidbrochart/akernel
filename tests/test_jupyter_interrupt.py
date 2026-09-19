import json
import signal
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from anyio import Event, fail_after, sleep
from jupyter_client import AsyncKernelManager
from jupyter_client.kernelspec import KernelSpecManager

from akernel.akernel import AKernel
from akernel.kernelspec import write_kernelspec


@pytest.fixture
def anyio_backend(request):
    return getattr(request, "param", "asyncio")


@pytest.fixture
def kernel_argv(request):
    backend = request.param
    return [
        sys.executable,
        "-c",
        (
            "from functools import partial; import anyio; import akernel.akernel as cli; "
            f"cli.run = partial(anyio.run, backend={backend!r}); cli.app()"
        ),
    ]


@pytest.fixture
async def standalone_kernel(tmp_path, kernel_argv):
    spec_dir = tmp_path / "akernel"
    spec_dir.mkdir()
    spec = json.loads(
        (
            Path(__file__).resolve().parents[1] / "share/jupyter/kernels/akernel/kernel.json"
        ).read_text()
    )
    spec["argv"][:1] = kernel_argv
    (spec_dir / "kernel.json").write_text(json.dumps(spec))
    manager = AsyncKernelManager(
        kernel_name="akernel",
        kernel_spec_manager=KernelSpecManager(kernel_dirs=[str(tmp_path)]),
    )
    client = None
    try:
        await manager.start_kernel()
        client = manager.client()
        client.start_channels()
        await client.wait_for_ready(timeout=10)
        yield manager, client
    finally:
        if manager.has_kernel:
            await manager.shutdown_kernel(now=True)
        if client is not None:
            client.stop_channels()


@pytest.mark.skipif(sys.platform == "win32", reason="Requires POSIX SIGINT")
@pytest.mark.parametrize("kernel_argv", ["asyncio", "trio"], indirect=True)
async def test_interrupt_aborts_requests_queued_while_blocked(standalone_kernel, tmp_path):
    manager, client = standalone_kernel
    reply = await client.execute("import time\nevents = []", reply=True, timeout=10)
    assert reply["content"]["status"] == "ok"
    ready = tmp_path / "ready"
    blocked = client.execute(
        f"from pathlib import Path\nPath({str(ready)!r}).touch()\ntime.sleep(60)\n1 + 2"
    )
    with fail_after(10):
        while not ready.exists():
            await sleep(0.01)
    queued = [
        client.execute("import anyio\nevents.append(3)"),
        client.execute("await anyio.sleep(0)\nevents.append(4)\n1 + 2"),
    ]
    # Let ZeroMQ deliver the queued requests while Python's event loop is blocked.
    await sleep(0.1)
    await manager.interrupt_kernel()
    replies = [await client.get_shell_msg(timeout=10) for _ in range(3)]
    statuses = {reply["parent_header"]["msg_id"]: reply["content"]["status"] for reply in replies}
    assert statuses == {blocked: "error", **dict.fromkeys(queued, "aborted")}
    reply = await client.execute(
        "assert events == []\nassert 'anyio' not in globals()", reply=True, timeout=10
    )
    assert reply["content"]["status"] == "ok"


@pytest.mark.parametrize("source", ["packaged", "installed"])
@pytest.mark.parametrize("kernel_argv", ["asyncio", "trio"], indirect=True)
@pytest.mark.parametrize(
    ("execute_in_thread", "code"),
    [
        (False, "ready_file.touch()\nawait anyio.sleep(60)"),
        (False, "ready_file.touch()\ntime.sleep(60)"),
        (False, "ready_file.touch()\nwhile True:\n    pass"),
        (
            False,
            (
                "class SlowRepr:\n    def __repr__(self):\n"
                "        ready_file.touch()\n        time.sleep(60)\nSlowRepr()"
            ),
        ),
        (True, "ready_file.touch()\nawait anyio.sleep(60)"),
    ],
    ids=["async", "sleep", "loop", "repr", "thread-async"],
)
async def test_jupyter_interrupt_preserves_kernel(
    tmp_path, monkeypatch, execute_in_thread, source, code, kernel_argv
):
    if sys.platform == "win32" and not execute_in_thread:
        pytest.skip("Jupyter's Windows interrupt event is not a POSIX SIGINT")
    name = "akernel-thread" if execute_in_thread else "akernel"
    if source == "installed":
        with monkeypatch.context() as patch:
            patch.setattr(sys, "prefix", str(tmp_path))
            write_kernelspec(name, name, mode="thread" if execute_in_thread else "process")
        root = tmp_path
    else:
        root = Path(__file__).resolve().parents[1]
    spec_path = root / "share" / "jupyter" / "kernels" / name / "kernel.json"
    spec = json.loads(spec_path.read_text())
    # Use this interpreter and checkout while retaining the shipped launch options.
    spec["argv"][:1] = kernel_argv
    launch_dir = tmp_path / "launch" / name
    launch_dir.mkdir(parents=True)
    (launch_dir / "kernel.json").write_text(json.dumps(spec))
    manager = AsyncKernelManager(
        kernel_name=name,
        kernel_spec_manager=KernelSpecManager(kernel_dirs=[str(launch_dir.parent)]),
    )
    client = None
    try:
        await manager.start_kernel()
        client = manager.client()
        client.start_channels()
        await client.wait_for_ready(timeout=10)
        ready = tmp_path / "ready"
        msg_id = client.execute(
            "import anyio, time\nfrom pathlib import Path\nsaved_value = 42\n"
            f"ready_file = Path({str(ready)!r})\n{code}"
        )
        # IOPub cannot flush a print while the main loop is blocked. Use a
        # filesystem marker to know the cell has started before sending SIGINT.
        with fail_after(10):
            while not ready.exists():
                await sleep(0.01)
        # Exercise the same interrupt-mode selection used by Jupyter Server.
        await manager.interrupt_kernel()
        reply = await client.get_shell_msg(timeout=10)
        assert reply["parent_header"]["msg_id"] == msg_id
        assert reply["content"]["status"] == "error"
        saw_interrupt = False
        with fail_after(10):
            while True:
                message = await client.get_iopub_msg()
                if (
                    message["parent_header"].get("msg_id") == msg_id
                    and message["msg_type"] == "error"
                ):
                    assert message["content"]["ename"] == "KeyboardInterrupt"
                    saw_interrupt = True
                if (
                    message["parent_header"].get("msg_id") == msg_id
                    and message["content"].get("execution_state") == "idle"
                ):
                    break
        assert saw_interrupt
        assert await manager.is_alive()
        reply = await client.execute("assert saved_value == 42", reply=True, timeout=10)
        assert reply["content"]["status"] == "ok"
        # An idle interrupt must also leave the kernel usable.
        if execute_in_thread:
            # Wait for acknowledgement before submitting a new request:
            # manager.interrupt_kernel() only sends the control message.
            client.control_channel.send(client.session.msg("interrupt_request"))
            reply = await client.get_control_msg(timeout=10)
            assert reply["msg_type"] == "interrupt_reply"
        else:
            await manager.interrupt_kernel()
            # SIGINT has no reply. A shell round trip lets the kernel process
            # the pending signal before we submit the next execution.
            reply = await client.kernel_info(reply=True, timeout=10)
            assert reply["msg_type"] == "kernel_info_reply"
        reply = await client.execute("assert saved_value == 42", reply=True, timeout=10)
        assert reply["content"]["status"] == "ok"
        await manager.shutdown_kernel()
    finally:
        if manager.has_kernel:
            await manager.shutdown_kernel(now=True)
        if client is not None:
            client.stop_channels()


@pytest.mark.parametrize("anyio_backend", ["asyncio", "trio"], indirect=True)
@pytest.mark.skipif(sys.platform == "win32", reason="AnyIO signal receivers require POSIX")
async def test_signal_receiver_closes_after_failure(monkeypatch):
    kernel = AKernel.__new__(AKernel)
    kernel.kernel = Mock(execute_in_thread=False)
    previous_handler = signal.getsignal(signal.SIGINT)
    active_handlers = []
    interrupted = Event()
    kernel.kernel.process_pending_interrupt.side_effect = interrupted.set

    async def start():
        active_handlers.append(signal.getsignal(signal.SIGINT))
        # A SIGINT outside cell execution must not raise into the event loop.
        signal.raise_signal(signal.SIGINT)
        with fail_after(2):
            await interrupted.wait()
        kernel.kernel.request_interrupt.assert_called_once_with()
        kernel.kernel.process_pending_interrupt.assert_called_once_with()
        raise RuntimeError("startup failed")

    monkeypatch.setattr(kernel, "_start", start)
    try:
        with pytest.RaisesGroup(pytest.RaisesExc(RuntimeError, match="startup failed")):
            await kernel.start()
        assert signal.getsignal(signal.SIGINT) not in active_handlers
    finally:
        # Restore the test runner's handler even with older AnyIO versions.
        signal.signal(signal.SIGINT, previous_handler)
