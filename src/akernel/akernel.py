from __future__ import annotations

import json
import signal
import sys
from types import FrameType
from typing import Annotated, Literal, cast

import zmq
from anyio import (
    Event,
    Future,
    create_memory_object_stream,
    create_task_group,
    open_signal_receiver,
    run,
)
from anyio.lowlevel import checkpoint
from cyclopts import App, Parameter

from .connect import connect_channel
from .execution import execute_cell
from .kernel import Kernel
from .kernelspec import write_kernelspec
from .message import deserialize, feed_identities

app = App()


@app.command()
def install(mode: Literal["process", "task", "thread"] = "process") -> None:
    """Install the subprocess kernel, or the in-process task or thread kernel."""
    kernel_name = {"process": "akernel", "task": "akernel-task", "thread": "akernel-thread"}[mode]
    write_kernelspec(kernel_name, f"Python 3 ({kernel_name})", mode=mode)


@app.command()
def launch(
    connection_file: Annotated[str, Parameter(alias=["-f"])],
    execute_in_thread: bool = False,
):
    """Launch the kernel.

    Args:
        connection_file: Path to the connection file.
        execute_in_thread: Whether to run user code in a thread.
    """
    akernel = AKernel(connection_file, execute_in_thread)
    run(akernel.start)


class AKernel:
    def __init__(self, connection_file, execute_in_thread=False):
        self._shutdown_reply_sent = Event()
        self._shell_receive: Future[list[bytes]] | None = None
        self._to_shell_send_stream, self._to_shell_receive_stream = create_memory_object_stream[
            list[bytes]
        ](float("inf"))
        self._from_shell_send_stream, self._from_shell_receive_stream = create_memory_object_stream[
            list[bytes]
        ]()
        self._to_control_send_stream, self._to_control_receive_stream = create_memory_object_stream[
            list[bytes]
        ]()
        self._from_control_send_stream, self._from_control_receive_stream = (
            create_memory_object_stream[list[bytes]]()
        )
        self._to_stdin_send_stream, self._to_stdin_receive_stream = create_memory_object_stream[
            list[bytes]
        ]()
        self._from_stdin_send_stream, self._from_stdin_receive_stream = create_memory_object_stream[
            list[bytes]
        ]()
        self._from_iopub_send_stream, self._from_iopub_receive_stream = create_memory_object_stream[
            list[bytes]
        ](max_buffer_size=float("inf"))
        self.kernel = Kernel(
            self._to_shell_receive_stream,
            self._from_shell_send_stream,
            self._to_control_receive_stream,
            self._from_control_send_stream,
            self._to_stdin_receive_stream,
            self._from_stdin_send_stream,
            self._from_iopub_send_stream,
            execute_in_thread,
            drain_shell=self.drain_shell,
        )
        with open(connection_file) as f:
            connection_cfg = json.load(f)
        self.kernel.key = cast(str, connection_cfg["key"])
        self.shell_channel = connect_channel("shell", connection_cfg)
        self.iopub_channel = connect_channel("iopub", connection_cfg)
        self.control_channel = connect_channel("control", connection_cfg)
        self.stdin_channel = connect_channel("stdin", connection_cfg)

    async def start(self) -> None:
        if sys.platform == "win32":
            await self._start()
            return

        with open_signal_receiver(signal.SIGINT) as signals:
            receiver_handler = signal.getsignal(signal.SIGINT)

            async def receive_interrupts() -> None:
                async for _ in signals:
                    self.kernel.process_pending_interrupt()

            def interrupt(signum: int, frame: FrameType | None) -> None:
                self.kernel.request_interrupt()
                # Preserve AnyIO's signal delivery and event-loop wakeup.
                if callable(receiver_handler):
                    receiver_handler(signum, frame)
                if not self.kernel.execute_in_thread:
                    while frame is not None:
                        if frame.f_code in (execute_cell.__code__, Kernel.show_result.__code__):
                            # An async receiver cannot run during blocking
                            # code. Raise only inside the cell's exception
                            # boundary, never into the event loop itself.
                            raise KeyboardInterrupt()
                        frame = frame.f_back

            signal.signal(signal.SIGINT, interrupt)
            async with create_task_group() as tasks:
                tasks.start_soon(receive_interrupts)
                try:
                    await self._start()
                finally:
                    tasks.cancel_scope.cancel()

    async def _start(self) -> None:
        async with (
            self._to_shell_send_stream,
            self._to_shell_receive_stream,
            self._from_shell_send_stream,
            self._from_shell_receive_stream,
            self._to_control_send_stream,
            self._to_control_receive_stream,
            self._from_control_send_stream,
            self._from_control_receive_stream,
            self._to_stdin_send_stream,
            self._to_stdin_receive_stream,
            self._from_stdin_send_stream,
            self._from_stdin_receive_stream,
            self._from_iopub_send_stream,
            self._from_iopub_receive_stream,
            self.shell_channel,
            self.control_channel,
            self.stdin_channel,
            self.iopub_channel,
            create_task_group() as tg,
        ):
            tg.start_soon(self.to_shell)
            tg.start_soon(self.from_shell)
            tg.start_soon(self.to_control)
            tg.start_soon(self.from_control)
            tg.start_soon(self.to_stdin)
            tg.start_soon(self.from_stdin)
            tg.start_soon(self.from_iopub)
            await self.kernel.start()
            # Receiving from the memory stream does not mean the reply has
            # reached the socket yet. Keep the forwarder alive until it has.
            await self._shutdown_reply_sent.wait()
            tg.cancel_scope.cancel()

    def drain_shell(self) -> None:
        # Include a socket receive that completed before its forwarding task
        # resumed. Clearing the reference prevents forwarding it twice.
        if self._shell_receive is not None and self._shell_receive.status is Future.Status.FINISHED:
            self.queue_shell(self._shell_receive.return_value)
            self._shell_receive = None
        # A blocking cell leaves Run All requests in ZeroMQ, outside the kernel's
        # memory stream. Move the currently available backlog into that stream
        # before Kernel.interrupt() snapshots it. Later requests remain usable.
        while True:
            try:
                msg = self.shell_channel.recv_multipart(flags=zmq.DONTWAIT)
            except zmq.Again:
                break
            self.queue_shell(msg)

    def queue_shell(self, msg: list[bytes]) -> None:
        self.kernel.register_shell_request(msg)
        self._to_shell_send_stream.send_nowait(msg)

    async def to_shell(self) -> None:
        while True:
            await checkpoint()
            future = self.shell_channel.arecv_multipart()
            self._shell_receive = future
            msg = await future
            if self._shell_receive is future:
                self._shell_receive = None
                self.queue_shell(msg)

    async def from_shell(self) -> None:
        async for msg in self._from_shell_receive_stream:
            await self.shell_channel.asend_multipart(msg, copy=True)

    async def to_control(self) -> None:
        while True:
            msg = await self.control_channel.arecv_multipart()
            await self._to_control_send_stream.send(msg)

    async def from_control(self) -> None:
        async for msg in self._from_control_receive_stream:
            await self.control_channel.asend_multipart(msg, copy=True)
            reply = deserialize(feed_identities(msg)[1])
            if reply["header"]["msg_type"] == "shutdown_reply" and not reply["content"]["restart"]:
                self._shutdown_reply_sent.set()

    async def to_stdin(self) -> None:
        while True:
            msg = await self.stdin_channel.arecv_multipart()
            await self._to_stdin_send_stream.send(msg)

    async def from_stdin(self) -> None:
        async for msg in self._from_stdin_receive_stream:
            await self.stdin_channel.asend_multipart(msg, copy=True)

    async def from_iopub(self) -> None:
        async for msg in self._from_iopub_receive_stream:
            await self.iopub_channel.asend_multipart(msg, copy=True)


if __name__ == "__main__":
    app()
