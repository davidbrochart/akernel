from types import SimpleNamespace

import pytest
from anyio import create_memory_object_stream, create_task_group, fail_after

from akernel.kernel import Kernel
from akernel.message import create_message, deserialize, feed_identities, serialize

pytestmark = pytest.mark.anyio


class TestStartup:
    @pytest.fixture(autouse=True)
    async def kernel_fixture(self, anyio_backend):
        async with create_task_group() as self.tasks:
            self.streams = [create_memory_object_stream(100) for _ in range(7)]
            self.kernel = Kernel(
                self.streams[0][1],
                self.streams[1][0],
                self.streams[2][1],
                self.streams[3][0],
                self.streams[4][1],
                self.streams[5][0],
                self.streams[6][0],
            )
            self.task = self.tasks.create_task(self.kernel.start())
            try:
                yield
            finally:
                self.kernel.stop_event.set()
                with fail_after(2):
                    await self.task
                for pair in self.streams:
                    for stream in pair:
                        await stream.aclose()

    async def receive(self, channel):
        with fail_after(2):
            parts = await self.streams[channel][1].receive()
        return deserialize(feed_identities(parts)[1])

    async def startup(self):
        for state in ("starting", "idle"):
            message = await self.receive(6)
            assert message["header"]["msg_type"] == "status"
            assert message["content"]["execution_state"] == state
            assert message["parent_header"] == {}

    async def request(self, msg_type, content):
        request = create_message(msg_type, content=content, address=b"client")
        parent_header = request["header"].copy()
        await self.streams[0][0].send(serialize(request, self.kernel.key))
        busy = await self.receive(6)
        reply = await self.receive(1)
        idle = await self.receive(6)
        for message in (busy, reply, idle):
            assert message["parent_header"] == parent_header
        assert busy["content"] == {"execution_state": "busy"}
        assert idle["content"] == {"execution_state": "idle"}
        assert reply["header"]["msg_type"] == msg_type.replace("_request", "_reply")
        return reply["content"]

    async def test_startup_publishes_idle(self):
        await self.startup()

    async def test_kernel_info_completes(self):
        await self.startup()
        reply = await self.request("kernel_info_request", {})
        assert reply["status"] == "ok"
        # Protocol 5.4+ requires an XPUB iopub_welcome handshake, which this
        # kernel's PUB transport does not implement.
        assert reply["protocol_version"] == "5.3"

    async def test_notebook_history_request_completes(self):
        await self.startup()
        reply = await self.request(
            "history_request", {"output": False, "raw": True, "hist_access_type": "tail", "n": 10}
        )
        assert reply == {"status": "ok", "history": []}

    async def test_comm_info_without_target(self):
        await self.startup()
        self.kernel.comm_manager.comms["widget"] = SimpleNamespace(target_name="widgets")
        reply = await self.request("comm_info_request", {})
        assert reply == {"status": "ok", "comms": {"widget": {"target_name": "widgets"}}}

    async def test_comm_info_filters_target(self):
        await self.startup()
        self.kernel.comm_manager.comms.update(
            {
                "widget": SimpleNamespace(target_name="widgets"),
                "other": SimpleNamespace(target_name="other"),
            }
        )
        reply = await self.request("comm_info_request", {"target_name": "widgets"})
        assert reply["comms"] == {"widget": {"target_name": "widgets"}}
        reply = await self.request("comm_info_request", {"target_name": "missing"})
        assert reply["comms"] == {}
