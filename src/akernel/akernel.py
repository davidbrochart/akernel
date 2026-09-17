from __future__ import annotations

import json
from typing import Annotated, cast

from anyio import Event, create_memory_object_stream, create_task_group, run
from cyclopts import App, Parameter

from .connect import connect_channel
from .kernel import Kernel
from .kernelspec import write_kernelspec
from .message import deserialize, feed_identities

app = App()


@app.command()
def install(execute_in_thread: bool = False) -> None:
    """Install the kernel, optionally executing user code in a thread."""
    kernel_name = "akernel-thread" if execute_in_thread else "akernel"
    write_kernelspec(kernel_name, f"Python 3 ({kernel_name})", execute_in_thread)


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
        self._to_shell_send_stream, self._to_shell_receive_stream = create_memory_object_stream[
            list[bytes]
        ]()
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
        )
        with open(connection_file) as f:
            connection_cfg = json.load(f)
        self.kernel.key = cast(str, connection_cfg["key"])
        self.shell_channel = connect_channel("shell", connection_cfg)
        self.iopub_channel = connect_channel("iopub", connection_cfg)
        self.control_channel = connect_channel("control", connection_cfg)
        self.stdin_channel = connect_channel("stdin", connection_cfg)

    async def start(self) -> None:
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

    async def to_shell(self) -> None:
        while True:
            msg = await self.shell_channel.arecv_multipart()
            await self._to_shell_send_stream.send(msg)

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
