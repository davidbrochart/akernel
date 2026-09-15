import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from anyio import Future, fail_after

from akernel.akernel import AKernel
from akernel.message import create_message, deserialize, feed_identities, serialize


class Channel:
    """Socket stand-in that detects use outside its context manager."""

    def __init__(self):
        self.incoming = asyncio.Queue()
        self.sent = asyncio.Queue()
        self.sending = asyncio.Event()
        self.allow_send = asyncio.Event()
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
            return await self.incoming.get()
        finally:
            self.readers -= 1

    def asend_multipart(self, message, **kwargs):
        assert self.open

        async def send():
            self.sending.set()
            await self.allow_send.wait()
            assert self.open
            await self.sent.put(deserialize(feed_identities(message)[1]))

        return send()


class TestShutdown(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.channels = {name: Channel() for name in ("shell", "control", "stdin", "iopub")}
        with TemporaryDirectory() as directory:
            path = Path(directory) / "connection.json"
            path.write_text(json.dumps({"key": "test"}))
            with patch(
                "akernel.akernel.connect_channel",
                side_effect=lambda name, cfg: self.channels[name],
            ):
                self.kernel = AKernel("", None, path)
        self.task = asyncio.create_task(self.kernel.start())
        await asyncio.wait_for(self.channels["iopub"].sent.get(), 2)

    async def asyncTearDown(self):
        if not self.task.done():
            self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)

    async def send(self, channel, kind, content):
        message = create_message(kind, content=content, address=b"client")
        await self.channels[channel].incoming.put(serialize(message, "test"))
        return message["header"]["msg_id"]

    async def test_waits_for_shutdown_reply_before_closing(self):
        control = self.channels["control"]
        control.allow_send.clear()
        msg_id = await self.send("control", "shutdown_request", {"restart": False})
        await asyncio.wait_for(control.sending.wait(), 2)
        self.assertFalse(self.task.done())
        self.assertTrue(control.open)
        control.allow_send.set()
        await asyncio.wait_for(self.task, 2)
        reply = control.sent.get_nowait()
        self.assertEqual(reply["header"]["msg_type"], "shutdown_reply")
        self.assertEqual(reply["parent_header"]["msg_id"], msg_id)
        self.assertEqual(reply["content"], {"restart": False})
        self.assertTrue(all(not channel.open for channel in self.channels.values()))


    async def test_shutdown_cancels_running_cells(self):
        await self.send("shell", "execute_request", {"code": "await asyncio.sleep(60)"})
        with fail_after(2):
            while not self.kernel.kernel.running_cells:
                await asyncio.sleep(0)
        tasks = list(self.kernel.kernel.running_cells.values())
        await self.send("control", "shutdown_request", {"restart": False})
        await asyncio.wait_for(self.task, 2)
        self.assertTrue(all(task.cancelled() for task in tasks))
        self.assertEqual(self.kernel.kernel.running_cells, {})

    async def test_cancellation_stops_readers_before_closing_sockets(self):
        self.task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await self.task
        self.assertTrue(all(not channel.open for channel in self.channels.values()))


class TestSocketFutures(IsolatedAsyncioTestCase):
    async def test_receivers_use_future_return_value(self):
        # AnyIO Future.wait() returns None; awaiting the future returns the frames.
        for name in ("shell", "control", "stdin"):
            with self.subTest(channel=name):
                frames = [b"message"]
                future = Future()
                future.return_value = frames
                kernel = AKernel.__new__(AKernel)
                channel = Mock()
                channel.arecv_multipart.return_value = future
                stream = Mock()
                stream.send = AsyncMock(side_effect=asyncio.CancelledError)
                setattr(kernel, f"{name}_channel", channel)
                setattr(kernel, f"_to_{name}_send_stream", stream)
                with self.assertRaises(asyncio.CancelledError):
                    await getattr(kernel, f"to_{name}")()
                stream.send.assert_awaited_once_with(frames)
