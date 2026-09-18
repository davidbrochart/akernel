import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, Mock, patch

import anyio.lowlevel
import pytest
import zmq
from anyio import (
    Event,
    Future,
    WouldBlock,
    create_memory_object_stream,
    create_task_group,
    fail_after,
)

from akernel.akernel import AKernel
from akernel.message import create_message, deserialize, feed_identities, serialize

pytestmark = pytest.mark.anyio


class Channel:
    """Socket stand-in that detects use outside its context manager."""

    def __init__(self):
        self.incoming_send, self.incoming_receive = create_memory_object_stream(100)
        self.sent_send, self.sent_receive = create_memory_object_stream(100)
        self.sending = Event()
        self.allow_send = Event()
        self.allow_send.set()
        self.open = False
        self.readers = 0

    async def __aenter__(self):
        self.open = True
        return self

    async def __aexit__(self, *args):
        assert self.readers == 0, "Socket closed before its reader stopped"
        self.open = False

    def arecv_multipart(self):
        return self.receive()

    async def receive(self):
        assert self.open
        self.readers += 1
        try:
            return await self.incoming_receive.receive()
        finally:
            self.readers -= 1

    def asend_multipart(self, message, **kwargs):
        assert self.open

        async def send():
            self.sending.set()
            await self.allow_send.wait()
            assert self.open
            await self.sent_send.send(deserialize(feed_identities(message)[1]))

        return send()


class TestShutdown:
    @pytest.fixture(autouse=True)
    async def kernel_fixture(self, anyio_backend):
        self.channels = {name: Channel() for name in ("shell", "control", "stdin", "iopub")}
        with TemporaryDirectory() as directory:
            path = Path(directory) / "connection.json"
            path.write_text(json.dumps({"key": "test"}))
            with patch(
                "akernel.akernel.connect_channel",
                side_effect=lambda name, cfg: self.channels[name],
            ):
                self.kernel = AKernel(path, False)
        async with create_task_group() as self.tasks:
            self.task = self.tasks.create_task(self.kernel._start())
            try:
                with fail_after(2):
                    await self.channels["iopub"].sent_receive.receive()
                yield
            finally:
                self.task.cancel()
                with fail_after(2):
                    await self.task.wait()
                for channel in self.channels.values():
                    for stream in (
                        channel.incoming_send,
                        channel.incoming_receive,
                        channel.sent_send,
                        channel.sent_receive,
                    ):
                        stream.close()

    async def send(self, channel, kind, content):
        message = create_message(kind, content=content, address=b"client")
        await self.channels[channel].incoming_send.send(serialize(message, "test"))
        return message["header"]["msg_id"]

    async def test_waits_for_shutdown_reply_before_closing(self):
        control = self.channels["control"]
        control.allow_send = Event()
        msg_id = await self.send("control", "shutdown_request", {"restart": False})
        with fail_after(2):
            await control.sending.wait()
        assert self.task.status is self.task.Status.PENDING
        assert control.open
        control.allow_send.set()
        with fail_after(2):
            await self.task
        reply = control.sent_receive.receive_nowait()
        assert reply["header"]["msg_type"] == "shutdown_reply"
        assert reply["parent_header"]["msg_id"] == msg_id
        assert reply["content"] == {"restart": False}
        assert all(not channel.open for channel in self.channels.values())

    async def test_shutdown_cancels_running_cells(self):
        await self.send("shell", "execute_request", {"code": "import anyio\nawait anyio.sleep(60)"})
        with fail_after(2):
            while not self.kernel.kernel.running_cells:
                await anyio.lowlevel.checkpoint()
        tasks = list(self.kernel.kernel.running_cells.values())
        await self.send("control", "shutdown_request", {"restart": False})
        with fail_after(2):
            await self.task
        assert all(task.status is not task.Status.PENDING for task in tasks)
        assert self.kernel.kernel.running_cells == {}

    async def test_cancellation_stops_readers_before_closing_sockets(self):
        self.task.cancel()
        with fail_after(2):
            await self.task.wait()
        assert self.task.status is self.task.Status.CANCELLED
        assert all(not channel.open for channel in self.channels.values())


class TestSocketFutures:
    async def test_interrupt_drains_completed_receive_once(self):
        first, second = [b"first"], [b"second"]
        receive = Future()
        next_receive = Future()
        kernel = AKernel.__new__(AKernel)
        kernel.kernel = Mock()
        kernel._shell_receive = None
        kernel.shell_channel = Mock()
        kernel.shell_channel.arecv_multipart.side_effect = [receive, next_receive]
        kernel.shell_channel.recv_multipart.side_effect = [second, zmq.Again()]
        send, stream = create_memory_object_stream(100)
        kernel._to_shell_send_stream = send
        async with send, stream, create_task_group() as tasks:
            tasks.start_soon(kernel.to_shell)
            with fail_after(2):
                while kernel._shell_receive is not receive:
                    await anyio.lowlevel.checkpoint()
            receive.return_value = first
            # Drain before the forwarding task can resume its completed await.
            kernel.drain_shell()
            with fail_after(2):
                while kernel._shell_receive is not next_receive:
                    await anyio.lowlevel.checkpoint()
            assert stream.receive_nowait() == first
            assert stream.receive_nowait() == second
            with pytest.raises(WouldBlock):
                stream.receive_nowait()
            assert kernel.kernel.register_shell_request.call_count == 2
            tasks.cancel_scope.cancel()

    @pytest.mark.parametrize("name", ["shell", "control", "stdin"])
    async def test_receivers_use_future_return_value(self, name):
        # AnyIO Future.wait() returns None; awaiting the future returns the frames.
        frames = [b"message"]
        future = Future()
        future.return_value = frames
        kernel = AKernel.__new__(AKernel)
        kernel.kernel = Mock()
        channel = Mock()
        channel.arecv_multipart.return_value = future
        stream = Mock()
        stream.send = AsyncMock(side_effect=RuntimeError("stop receiving"))
        stream.send_nowait = Mock(side_effect=RuntimeError("stop receiving"))
        setattr(kernel, f"{name}_channel", channel)
        setattr(kernel, f"_to_{name}_send_stream", stream)
        with pytest.raises(RuntimeError, match="stop receiving"):
            await getattr(kernel, f"to_{name}")()
        if name == "shell":
            stream.send_nowait.assert_called_once_with(frames)
        else:
            stream.send.assert_awaited_once_with(frames)
