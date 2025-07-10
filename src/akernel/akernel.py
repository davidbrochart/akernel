from __future__ import annotations

import json
from typing import Optional, cast

import typer
from anyio import create_memory_object_stream, create_task_group, run, sleep_forever

from .connect import connect_channel
from .kernel import Kernel
from .kernelspec import write_kernelspec


cli = typer.Typer()


@cli.command()
def install(
    mode: str = typer.Argument("", help="Mode of the kernel to install."),
    cache_dir: Optional[str] = typer.Option(
        None, "-c", help="Path to the cache directory, if mode is 'cache'."
    ),
):
    kernel_name = "akernel"
    if mode:
        modes = mode.split("-")
        modes.sort()
        mode = "-".join(modes)
        kernel_name += f"-{mode}"
    display_name = f"Python 3 ({kernel_name})"
    write_kernelspec(kernel_name, mode, display_name, cache_dir)


@cli.command()
def launch(
    mode: str = typer.Argument("", help="Mode of the kernel to launch."),
    cache_dir: Optional[str] = typer.Option(
        None, "-c", help="Path to the cache directory, if mode is 'cache'."
    ),
    connection_file: str = typer.Option(..., "-f", help="Path to the connection file."),
):
    akernel = AKernel(mode, cache_dir, connection_file)
    run(akernel.start)


class AKernel:
    def __init__(self, mode, cache_dir, connection_file):
        self._to_shell_send_stream, self._to_shell_receive_stream = create_memory_object_stream[list[bytes]]()
        self._from_shell_send_stream, self._from_shell_receive_stream = create_memory_object_stream[list[bytes]]()
        self._to_control_send_stream, self._to_control_receive_stream = create_memory_object_stream[list[bytes]]()
        self._from_control_send_stream, self._from_control_receive_stream = create_memory_object_stream[list[bytes]]()
        self._to_stdin_send_stream, self._to_stdin_receive_stream = create_memory_object_stream[list[bytes]]()
        self._from_stdin_send_stream, self._from_stdin_receive_stream = create_memory_object_stream[list[bytes]]()
        self._from_iopub_send_stream, self._from_iopub_receive_stream = create_memory_object_stream[list[bytes]](max_buffer_size=float("inf"))
        self.kernel = Kernel(
            self._to_shell_receive_stream,
            self._from_shell_send_stream,
            self._to_control_receive_stream,
            self._from_control_send_stream,
            self._to_stdin_receive_stream,
            self._from_stdin_send_stream,
            self._from_iopub_send_stream,
            mode,
            cache_dir,
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
            create_task_group() as tg,
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
        ):
            tg.start_soon(self.kernel.start)
            tg.start_soon(self.to_shell)
            tg.start_soon(self.from_shell)
            tg.start_soon(self.to_control)
            tg.start_soon(self.from_control)
            tg.start_soon(self.to_stdin)
            tg.start_soon(self.from_stdin)
            tg.start_soon(self.from_iopub)
            await sleep_forever()

    async def to_shell(self) -> None:
        while True:
            msg = await self.shell_channel.arecv_multipart().wait()
            await self._to_shell_send_stream.send(msg)

    async def from_shell(self) -> None:
        async for msg in self._from_shell_receive_stream:
            await self.shell_channel.asend_multipart(msg, copy=True).wait()

    async def to_control(self) -> None:
        while True:
            msg = await self.control_channel.arecv_multipart().wait()
            await self._to_control_send_stream.send(msg)

    async def from_control(self) -> None:
        async for msg in self._from_control_receive_stream:
            await self.control_channel.asend_multipart(msg, copy=True).wait()

    async def to_stdin(self) -> None:
        while True:
            msg = await self.stdin_channel.arecv_multipart().wait()
            await self._to_stdin_send_stream.send(msg)

    async def from_stdin(self) -> None:
        async for msg in self._from_stdin_receive_stream:
            await self.stdin_channel.asend_multipart(msg, copy=True).wait()

    async def from_iopub(self) -> None:
        async for msg in self._from_iopub_receive_stream:
            await self.iopub_channel.asend_multipart(msg, copy=True).wait()


if __name__ == "__main__":
    cli()
