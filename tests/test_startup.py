import asyncio
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

from anyio import create_memory_object_stream

from akernel.kernel import Kernel
from akernel.message import create_message, deserialize, feed_identities, serialize


class TestStartup(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.streams = [create_memory_object_stream(100) for _ in range(7)]
        self.kernel = Kernel(
            self.streams[0][1], self.streams[1][0],
            self.streams[2][1], self.streams[3][0],
            self.streams[4][1], self.streams[5][0], self.streams[6][0],
        )
        self.task = asyncio.create_task(self.kernel.start())

    async def asyncTearDown(self):
        self.kernel.stop_event.set()
        await asyncio.wait_for(self.task, 2)
        for pair in self.streams:
            for stream in pair:
                await stream.aclose()

    async def receive(self, channel):
        parts = await asyncio.wait_for(self.streams[channel][1].receive(), 2)
        return deserialize(feed_identities(parts)[1])

    async def startup(self):
        for state in ("starting", "idle"):
            message = await self.receive(6)
            self.assertEqual(message["header"]["msg_type"], "status")
            self.assertEqual(message["content"]["execution_state"], state)
            self.assertEqual(message["parent_header"], {})

    async def request(self, msg_type, content):
        request = create_message(msg_type, content=content, address=b"client")
        parent_header = request["header"].copy()
        await self.streams[0][0].send(serialize(request, self.kernel.key))
        busy = await self.receive(6)
        reply = await self.receive(1)
        idle = await self.receive(6)
        for message in (busy, reply, idle):
            self.assertEqual(message["parent_header"], parent_header)
        self.assertEqual(busy["content"], {"execution_state": "busy"})
        self.assertEqual(idle["content"], {"execution_state": "idle"})
        self.assertEqual(reply["header"]["msg_type"], msg_type.replace("_request", "_reply"))
        return reply["content"]

    async def test_startup_publishes_idle(self):
        await self.startup()

    async def test_kernel_info_completes(self):
        await self.startup()
        reply = await self.request("kernel_info_request", {})
        self.assertEqual(reply["status"], "ok")
        # Protocol 5.4+ requires an XPUB iopub_welcome handshake, which this
        # kernel's PUB transport does not implement.
        self.assertEqual(reply["protocol_version"], "5.3")

    async def test_notebook_history_request_completes(self):
        await self.startup()
        reply = await self.request(
            "history_request", {"output": False, "raw": True, "hist_access_type": "tail", "n": 10}
        )
        self.assertEqual(reply, {"status": "ok", "history": []})

    async def test_comm_info_without_target(self):
        await self.startup()
        self.kernel.comm_manager.comms["widget"] = SimpleNamespace(target_name="widgets")
        reply = await self.request("comm_info_request", {})
        self.assertEqual(reply, {"status": "ok", "comms": {"widget": {"target_name": "widgets"}}})

    async def test_comm_info_filters_target(self):
        await self.startup()
        self.kernel.comm_manager.comms.update({
            "widget": SimpleNamespace(target_name="widgets"),
            "other": SimpleNamespace(target_name="other"),
        })
        reply = await self.request("comm_info_request", {"target_name": "widgets"})
        self.assertEqual(reply["comms"], {"widget": {"target_name": "widgets"}})
        reply = await self.request("comm_info_request", {"target_name": "missing"})
        self.assertEqual(reply["comms"], {})
