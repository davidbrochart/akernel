import threading
from unittest.mock import Mock, patch

import pytest
from anyio import (
    Event,
    create_memory_object_stream,
    create_task_group,
    fail_after,
    sleep,
)
from anyio.streams.stapled import StapledObjectStream
from rich.text import Text

from akernel.kernel import Kernel
from akernel.message import create_message, deserialize, feed_identities, serialize

pytestmark = pytest.mark.anyio


class TestInterrupt:
    execute_in_thread = False

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
                execute_in_thread=self.execute_in_thread,
            )
            self.shell_stream = StapledObjectStream(self.streams[0][0], self.streams[1][1])
            self.control_stream = StapledObjectStream(self.streams[2][0], self.streams[3][1])
            self.iopub_stream = self.streams[6][1]
            self.task = self.tasks.create_task(self.kernel.start())
            await self.receive(self.iopub_stream)
            await self.receive(self.iopub_stream)
            try:
                yield
            finally:
                self.kernel.stop_event.set()
                with fail_after(2):
                    await self.task
                for pair in self.streams:
                    for stream in pair:
                        stream.close()

    async def receive(self, stream):
        with fail_after(2):
            frames = await stream.receive()
        return deserialize(feed_identities(frames)[1])

    async def execute(self, code):
        message = create_message("execute_request", content={"code": code, "allow_stdin": True})
        with fail_after(2):
            await self.shell_stream.send(serialize(message, self.kernel.key))
        return message["header"]["msg_id"]

    async def wait_for_output(self, msg_id, kind):
        while True:
            message = await self.receive(self.iopub_stream)
            if (
                message["parent_header"].get("msg_id") == msg_id
                and message["header"]["msg_type"] == kind
            ):
                return message

    async def assert_finished(self, msg_id, status):
        reply = await self.receive(self.shell_stream)
        assert reply["parent_header"]["msg_id"] == msg_id
        assert reply["content"]["status"] == status
        while True:
            message = await self.wait_for_output(msg_id, "status")
            if message["content"]["execution_state"] == "idle":
                break

    async def test_interrupt_and_execute_again(self):
        first = await self.execute("import anyio\nprint('started')\nawait anyio.sleep(60)")
        await self.wait_for_output(first, "stream")
        self.kernel.interrupt()
        error = await self.wait_for_output(first, "error")
        traceback = Text.from_ansi("\n".join(error["content"]["traceback"])).plain
        assert "await anyio.sleep(60)" in traceback
        assert "KeyboardInterrupt" in traceback
        assert "Cell" in traceback
        await self.assert_finished(first, "error")
        second = await self.execute("'NEW'")
        output = await self.wait_for_output(second, "stream")
        assert output["content"]["text"] == "'NEW'\n"
        await self.assert_finished(second, "ok")

    @pytest.mark.parametrize("exception", ["KeyboardInterrupt", "ValueError"])
    async def test_user_exception_preserves_nested_traceback(self, exception):
        msg_id = await self.execute(f"def fail():\n    raise {exception}()\nfail()")
        error = await self.wait_for_output(msg_id, "error")
        assert error["content"]["ename"] == exception
        traceback = Text.from_ansi("\n".join(error["content"]["traceback"])).plain
        assert f"raise {exception}()" in traceback
        assert "fail()" in traceback
        await self.assert_finished(msg_id, "error")

    async def test_interrupt_chained_cells(self):
        first = await self.execute("import anyio\nprint('started')\nawait anyio.sleep(60)")
        await self.wait_for_output(first, "stream")
        second = await self.execute("print('must not execute')")
        # Wait until the queued execution has been registered.
        for _ in range(100):
            if len(self.kernel.running_cells) == 2:
                break
            await sleep(0.001)
        assert len(self.kernel.running_cells) == 2
        self.kernel.interrupt()
        replies = [await self.receive(self.shell_stream) for _ in range(2)]
        assert {r["parent_header"]["msg_id"] for r in replies} == {first, second}
        assert all(r["content"]["status"] == "error" for r in replies)
        third = await self.execute("'NEXT'")
        output = await self.wait_for_output(third, "stream")
        assert output["content"]["text"] == "'NEXT'\n"
        await self.assert_finished(third, "ok")

    async def test_interrupt_while_queued_cell_is_being_dispatched(self):
        first = await self.execute("import anyio\nprint('started')\nawait anyio.sleep(60)")
        await self.wait_for_output(first, "stream")
        dispatching = Event()
        resume = Event()
        original_send = self.kernel.from_iopub_send_stream.send

        async def send(frames):
            message = deserialize(feed_identities(frames)[1])
            if message["header"]["msg_type"] == "execute_input":
                dispatching.set()
                await resume.wait()
            await original_send(frames)

        with patch.object(self.kernel.from_iopub_send_stream, "send", send):
            second = await self.execute("queued_cell_ran = True")
            with fail_after(2):
                await dispatching.wait()
            self.kernel.interrupt()
            resume.set()
            replies = [await self.receive(self.shell_stream) for _ in range(2)]
        statuses = {r["parent_header"]["msg_id"]: r["content"]["status"] for r in replies}
        assert statuses == {first: "error", second: "aborted"}
        assert "queued_cell_ran" not in self.kernel.globals
        third = await self.execute("'NEXT'")
        output = await self.wait_for_output(third, "stream")
        assert output["content"]["text"] == "'NEXT'\n"
        await self.assert_finished(third, "ok")

    async def test_cells_share_state_and_execute_sequentially(self):
        # execute() creates a distinct client session for every request.
        first = await self.execute("import anyio\nawait anyio.sleep(0.05)\nvalues = [1]")
        second = await self.execute("values.append(2)")
        replies = [await self.receive(self.shell_stream) for _ in range(2)]
        assert {r["parent_header"]["msg_id"] for r in replies} == {first, second}
        assert all(r["content"]["status"] == "ok" for r in replies)
        assert self.kernel.globals["values"] == [1, 2]
        # Repeated code must execute its side effects every time.
        third = await self.execute("values.append(2)")
        await self.assert_finished(third, "ok")
        assert self.kernel.globals["values"] == [1, 2, 2]

    async def test_control_interrupt(self):
        first = await self.execute("import anyio\nprint('started')\nawait anyio.sleep(60)")
        await self.wait_for_output(first, "stream")
        message = create_message("interrupt_request")
        await self.control_stream.send(serialize(message, self.kernel.key))
        reply = await self.receive(self.control_stream)
        assert reply["header"]["msg_type"] == "interrupt_reply"
        await self.assert_finished(first, "error")

    async def test_shutdown_while_cell_is_running(self):
        first = await self.execute("import anyio\nprint('started')\nawait anyio.sleep(60)")
        await self.wait_for_output(first, "stream")
        # The fixture must stop both the cell and any worker thread.


class TestThreadInterrupt(TestInterrupt):
    execute_in_thread = True

    async def test_blocking_cell_completes_normally_after_interrupt(self):
        release = threading.Event()
        self.kernel.init_kernel()
        self.kernel.globals["release"] = release
        try:
            first = await self.execute("print('started')\nrelease.wait()\n'OLD'")
            await self.wait_for_output(first, "stream")
            self.kernel.interrupt()
            second = await self.execute("'NEW'")
            # Neither the blocked cell nor its successor can finish yet.
            with pytest.raises(TimeoutError):
                with fail_after(0.1):
                    await self.shell_stream.receive()
            while self.iopub_stream.statistics().current_buffer_used:
                message = await self.receive(self.iopub_stream)
                assert message["header"]["msg_type"] != "error"
                assert message["content"].get("execution_state") != "idle"
            release.set()
            replies = [await self.receive(self.shell_stream) for _ in range(2)]
            assert {r["parent_header"]["msg_id"] for r in replies} == {first, second}
            assert all(r["content"]["status"] == "ok" for r in replies)
            outputs = {first: [], second: []}
            finished = set()
            while len(finished) < 2:
                message = await self.receive(self.iopub_stream)
                parent = message["parent_header"]["msg_id"]
                assert message["header"]["msg_type"] != "error"
                if message["header"]["msg_type"] == "stream":
                    outputs[parent].append(message["content"]["text"])
                if message["content"].get("execution_state") == "idle":
                    finished.add(parent)
            assert outputs == {first: ["'OLD'\n"], second: ["'NEW'\n"]}
        finally:
            release.set()

    async def test_interrupt_waits_for_blocking_call_to_reach_checkpoint(self):
        release = threading.Event()
        self.kernel.init_kernel()
        self.kernel.globals["release"] = release
        try:
            first = await self.execute(
                "import anyio\nprint('started')\nrelease.wait()\nawait anyio.sleep(60)"
            )
            await self.wait_for_output(first, "stream")
            self.kernel.interrupt()
            with pytest.raises(TimeoutError):
                with fail_after(0.1):
                    await self.iopub_stream.receive()
            with pytest.raises(TimeoutError):
                with fail_after(0.1):
                    await self.shell_stream.receive()
            release.set()
            error = await self.wait_for_output(first, "error")
            assert error["content"]["ename"] == "KeyboardInterrupt"
            assert (
                "await anyio.sleep(60)"
                in Text.from_ansi("\n".join(error["content"]["traceback"])).plain
            )
            await self.assert_finished(first, "error")
        finally:
            release.set()


class TestPluginInterrupt:
    @pytest.fixture(autouse=True)
    async def task_group(self, anyio_backend):
        async with create_task_group() as self.tasks:
            yield
            self.tasks.cancel_scope.cancel()

    async def test_stop_during_worker_startup(self):
        try:
            from fps_akernel_task.akernel_task import AKernelTask
        except ModuleNotFoundError:
            pytest.skip("fps-akernel-task is not installed")
        for _ in range(10):
            plugin = AKernelTask(execute_in_thread=True)
            task = self.tasks.create_task(plugin.start())
            with fail_after(2):
                await plugin.started.wait()
            await sleep(0)
            await plugin.stop()
            with fail_after(2):
                await task

    async def test_stop_with_unread_reply(self):
        try:
            from fps_akernel_task.akernel_task import AKernelTask
        except ModuleNotFoundError:
            pytest.skip("fps-akernel-task is not installed")
        plugin = AKernelTask()
        task = self.tasks.create_task(plugin.start())
        try:
            with fail_after(2):
                await plugin.started.wait()
            request = create_message("execute_request", content={"code": "1 + 1"})
            await plugin.shell_stream.send(serialize(request, plugin.kernel.key))
            for _ in range(100):
                if plugin.kernel._finishing_cells:
                    break
                await sleep(0.001)
            assert plugin.kernel._finishing_cells
        finally:
            await plugin.stop()
            with fail_after(2):
                await task

    async def test_plugin_forwards_interrupt(self):
        try:
            from fps_akernel_task.akernel_task import AKernelTask
        except ModuleNotFoundError:
            pytest.skip("fps-akernel-task is not installed")
        plugin = AKernelTask()
        plugin.kernel = Mock()
        await plugin.interrupt()
        plugin.kernel.interrupt.assert_called_once_with()
        # This test does not start the plugin's streams.
        for name, value in vars(plugin).items():
            if name.endswith("_stream") and hasattr(value, "close"):
                value.close()

    @pytest.mark.parametrize("execute_in_thread", [False, True])
    async def test_plugin_interrupts_both_modes(self, execute_in_thread):
        try:
            from fps_akernel_task.akernel_task import AKernelTask
        except ModuleNotFoundError:
            pytest.skip("fps-akernel-task is not installed")
        plugin = AKernelTask(execute_in_thread=execute_in_thread)
        task = self.tasks.create_task(plugin.start())

        async def receive(stream):
            with fail_after(2):
                frames = await stream.receive()
            return deserialize(feed_identities(frames)[1])

        try:
            with fail_after(2):
                await plugin.started.wait()
            for _ in range(2):
                await receive(plugin.iopub_stream)
            request = create_message(
                "execute_request",
                content={"code": "import anyio\nprint('ready')\nawait anyio.sleep(60)"},
            )
            await plugin.shell_stream.send(serialize(request, plugin.kernel.key))
            while (await receive(plugin.iopub_stream))["header"]["msg_type"] != "stream":
                pass
            await plugin.interrupt()
            reply = await receive(plugin.shell_stream)
            assert reply["parent_header"]["msg_id"] == request["header"]["msg_id"]
            assert reply["content"]["status"] == "error"
            while True:
                message = await receive(plugin.iopub_stream)
                if message["content"].get("execution_state") == "idle":
                    break
        finally:
            await plugin.stop()
            with fail_after(2):
                await task
