from __future__ import annotations

import asyncio
import sys
import platform
import json
from io import StringIO
from contextvars import ContextVar
from typing import Dict, Any, List, Union, Awaitable, cast

from anyio import Event, create_task_group, sleep
import comm  # type: ignore
from akernel.comm.manager import CommManager
from akernel.display import display
import akernel.IPython
from akernel.IPython import core
from .connect import connect_channel
from .message import create_message, feed_identities, deserialize, serialize
from .execution import pre_execute, cache_execution
from .traceback import get_traceback
from . import __version__


PARENT_VAR: ContextVar = ContextVar("parent")
IDENTS_VAR: ContextVar = ContextVar("idents")

KERNEL: "Kernel"


sys.modules["IPython.display"] = display
sys.modules["IPython"] = akernel.IPython
sys.modules["IPython.core"] = core


class Kernel:
    stop_event: Event
    restart: bool
    key: str
    comm_manager: CommManager
    kernel_mode: str
    cell_done: Dict[int, Event]
    running_cells: Dict[int, asyncio.Task]
    task_i: int
    execution_count: int
    execution_state: str
    globals: Dict[str, Dict[str, Any]]
    locals: Dict[str, Dict[str, Any]]
    _multi_kernel: bool | None
    _cache_kernel: bool | None
    _react_kernel: bool | None
    kernel_initialized: set[str]
    cache: Dict[str, Any] | None

    def __init__(
        self,
        to_shell_receive_stream,
        from_shell_send_stream,
        to_control_receive_stream,
        from_control_send_stream,
        to_stdin_receive_stream,
        from_stdin_send_stream,
        from_iopub_send_stream,
        kernel_mode: str = "",
        cache_dir: str | None = None,
    ):
        global KERNEL
        KERNEL = self
        self.comm_manager = CommManager()
        comm.get_comm_manager = lambda: self.comm_manager

        self.to_shell_receive_stream = to_shell_receive_stream
        self.from_shell_send_stream = from_shell_send_stream
        self.to_control_receive_stream = to_control_receive_stream
        self.from_control_send_stream = from_control_send_stream
        self.to_stdin_receive_stream = to_stdin_receive_stream
        self.from_stdin_send_stream = from_stdin_send_stream
        self.from_iopub_send_stream = from_iopub_send_stream

        self.kernel_mode = kernel_mode
        self.cache_dir = cache_dir
        self._concurrent_kernel = None
        self._multi_kernel = None
        self._cache_kernel = None
        self._react_kernel = None
        self.kernel_initialized = set()
        self.globals = {}
        self.locals = {}
        self._chain_execution = not self.concurrent_kernel
        self.cell_done = {}
        self.running_cells = {}
        self.task_i = 0
        self.execution_count = 1
        self.execution_state = "starting"
        self.restart = False
        self.interrupted = False
        self.msg_cnt = 0
        if self.cache_kernel:
            from .cache import cache

            self.cache = cache(cache_dir)
        else:
            self.cache = None
        self.stop_event = Event()
        self.key = "0"

    def chain_execution(self) -> None:
        self._chain_execution = True

    def unchain_execution(self) -> None:
        self._chain_execution = False

    @property
    def concurrent_kernel(self):
        if self._concurrent_kernel is None:
            self._concurrent_kernel = "concurrent" in self.kernel_mode
        return self._concurrent_kernel

    @property
    def multi_kernel(self):
        if self._multi_kernel is None:
            self._multi_kernel = "multi" in self.kernel_mode
        return self._multi_kernel

    @property
    def cache_kernel(self):
        if self._cache_kernel is None:
            self._cache_kernel = "cache" in self.kernel_mode
        return self._cache_kernel

    @property
    def react_kernel(self):
        if self._react_kernel is None:
            self._react_kernel = "react" in self.kernel_mode
        return self._react_kernel

    def init_kernel(self, namespace):
        if namespace in self.kernel_initialized:
            return

        self.globals[namespace] = {
            "ainput": self.ainput,
            "asyncio": asyncio,
            "print": self.print,
            "__task__": self.task,
            "__chain_execution__": self.chain_execution,
            "__unchain_execution__": self.unchain_execution,
            "_": None,
        }
        self.locals[namespace] = {}
        if self.react_kernel:
            code = (
                "import ipyx, ipywidgets;globals().update({'ipyx': ipyx, 'ipywidgets': ipywidgets})"
            )
            exec(code, self.globals[namespace], self.locals[namespace])

        self.kernel_initialized.add(namespace)

    def get_namespace(self, parent_header) -> str:
        if self.multi_kernel:
            return parent_header["session"]

        return "namespace"

    def interrupt(self):
        self.interrupted = True
        for task in self.running_cells.values():
            task.cancel()
        self.running_cells = {}

    async def start(self) -> None:
        async with create_task_group() as self.task_group:
            msg = self.create_message("status", content={"execution_state": self.execution_state})
            to_send = serialize(msg, self.key)
            await self.from_iopub_send_stream.send(to_send)
            self.execution_state = "idle"
            while True:
                try:
                    await self._start()
                except KeyboardInterrupt:
                    self.interrupt()
                else:
                    if not self.restart:
                        break
                finally:
                    self.task_group.cancel_scope.cancel()

    async def _start(self) -> None:
        self.task_group.start_soon(self.listen_shell)
        self.task_group.start_soon(self.listen_control)
        while True:
            # run until shutdown request
            await self.stop_event.wait()
            if self.restart:
                # kernel restart
                self.stop_event = Event()
            else:
                # kernel shutdown
                break

    async def listen_shell(self) -> None:
        while True:
            # let a chance to execute a blocking cell
            await sleep(0)
            # if there was a blocking cell execution, and it was interrupted,
            # let's ignore all the following execution requests until the pipe
            # is empty
            if self.interrupted and self.to_shell_receive_stream.statistics().tasks_waiting_send == 0:
                self.interrupted = False
            msg_list = await self.to_shell_receive_stream.receive()
            idents, msg_list = feed_identities(msg_list)
            msg = deserialize(msg_list)
            msg_type = msg["header"]["msg_type"]
            parent_header = msg["header"]
            parent = msg
            if msg_type == "kernel_info_request":
                msg = self.create_message(
                    "kernel_info_reply",
                    parent_header=parent_header,
                    content={
                        "status": "ok",
                        "protocol_version": "5.5",
                        "implementation": "akernel",
                        "implementation_version": __version__,
                        "language_info": {
                            "name": "python",
                            "version": platform.python_version(),
                            "mimetype": "text/x-python",
                            "file_extension": ".py",
                        },
                        "banner": "Python " + sys.version,
                    },
                    address=idents[0],
                )
                to_send = serialize(msg, self.key)
                await self.from_shell_send_stream.send(to_send)
                msg = self.create_message(
                    "status",
                    parent_header=parent_header,
                    content={"execution_state": self.execution_state},
                )
                to_send = serialize(msg, self.key)
                await self.from_iopub_send_stream.send(to_send)
            elif msg_type == "execute_request":
                self.execution_state = "busy"
                code = msg["content"]["code"]
                msg = self.create_message(
                    "status",
                    parent_header=parent_header,
                    content={"execution_state": self.execution_state},
                )
                to_send = serialize(msg, self.key)
                await self.from_iopub_send_stream.send(to_send)
                if self.interrupted:
                    await self.finish_execution(idents, parent_header, None, no_exec=True)
                    continue
                msg = self.create_message(
                    "execute_input",
                    parent_header=parent_header,
                    content={"code": code, "execution_count": self.execution_count},
                )
                to_send = serialize(msg, self.key)
                await self.from_iopub_send_stream.send(to_send)
                namespace = self.get_namespace(parent_header)
                self.init_kernel(namespace)
                traceback, exception, cache_info = pre_execute(
                    code,
                    self.globals[namespace],
                    self.locals[namespace],
                    self.task_i,
                    self.execution_count,
                    react=self.react_kernel,
                    cache=self.cache,
                )
                if cache_info["cached"]:
                    await self.finish_execution(
                        idents,
                        parent_header,
                        self.execution_count,
                        result=cache_info["result"],
                    )
                    self.execution_count += 1
                elif traceback:
                    await self.finish_execution(
                        idents,
                        parent_header,
                        self.execution_count,
                        traceback=traceback,
                        exception=exception,
                    )
                else:
                    task = asyncio.create_task(
                        self.execute_and_finish(
                            idents,
                            parent,
                            self.task_i,
                            self.execution_count,
                            code,
                            cache_info,
                        )
                    )
                    self.cell_done[self.task_i] = asyncio.Event()
                    self.running_cells[self.task_i] = task
                    self.task_i += 1
                    self.execution_count += 1
            elif msg_type == "comm_info_request":
                self.execution_state = "busy"
                msg2 = self.create_message(
                    "status",
                    parent_header=parent_header,
                    content={"execution_state": self.execution_state},
                )
                to_send = serialize(msg2, self.key)
                await self.from_iopub_send_stream.send(to_send)
                if "target_name" in msg["content"]:
                    target_name = msg["content"]["target_name"]
                    comms: List[str] = []
                    msg2 = self.create_message(
                        "comm_info_reply",
                        parent_header=parent_header,
                        content={
                            "status": "ok",
                            "comms": {comm_id: {"target_name": target_name} for comm_id in comms},
                        },
                        address=idents[0],
                    )
                    to_send = serialize(msg2, self.key)
                    await self.from_shell_send_stream.send(to_send)
                self.execution_state = "idle"
                msg2 = self.create_message(
                    "status",
                    parent_header=parent_header,
                    content={"execution_state": self.execution_state},
                )
                to_send = serialize(msg2, self.key)
                await self.from_iopub_send_stream.send(to_send)
            elif msg_type == "comm_msg":
                self.comm_manager.comm_msg(None, None, msg)  # type: ignore[arg-type]

    async def listen_control(self) -> None:
        while True:
            msg_list = await self.to_control_receive_stream.receive()
            idents, msg_list = feed_identities(msg_list)
            msg = deserialize(msg_list)
            msg_type = msg["header"]["msg_type"]
            parent_header = msg["header"]
            if msg_type == "shutdown_request":
                self.restart = msg["content"]["restart"]
                msg = self.create_message(
                    "shutdown_reply",
                    parent_header=parent_header,
                    content={"restart": self.restart},
                    address=idents[0],
                )
                to_send = serialize(msg, self.key)
                await self.from_control_send_stream.send(to_send)
                if self.restart:
                    self.execution_count = 1
                self.stop_event.set()

    async def execute_and_finish(
        self,
        idents: List[bytes],
        parent: Dict[str, Any],
        task_i: int,
        execution_count: int,
        code: str,
        cache_info: Dict[str, Any],
    ) -> None:
        prev_task_i = task_i - 1
        if self._chain_execution and prev_task_i in self.cell_done:
            await self.cell_done[prev_task_i].wait()
            del self.cell_done[prev_task_i]
        PARENT_VAR.set(parent)
        IDENTS_VAR.set(idents)
        parent_header = parent["header"]
        traceback, exception = [], None
        namespace = self.get_namespace(parent_header)
        try:
            result = await self.locals[namespace][f"__async_cell{task_i}__"]()
        except KeyboardInterrupt:
            self.interrupt()
        except Exception as e:
            exception = e
            traceback = get_traceback(code, e, execution_count)
        else:
            await self.show_result(result, self.globals[namespace], parent_header)
            cache_execution(self.cache, cache_info, self.globals[namespace], result)
        finally:
            self.cell_done[task_i].set()
            del self.locals[namespace][f"__async_cell{task_i}__"]
            await self.finish_execution(
                idents,
                parent_header,
                execution_count,
                exception=exception,
                traceback=traceback,
            )
            if task_i in self.running_cells:
                del self.running_cells[task_i]

    async def finish_execution(
        self,
        idents: List[bytes],
        parent_header: Dict[str, Any],
        execution_count: int | None,
        exception: Exception | None = None,
        no_exec: bool = False,
        traceback: List[str] = [],
        result=None,
    ) -> None:
        if result:
            namespace = self.get_namespace(parent_header)
            await self.show_result(result, self.globals[namespace], parent_header)
        if no_exec:
            status = "aborted"
        else:
            if traceback:
                status = "error"
                assert exception is not None
                msg = create_message(
                    "error",
                    parent_header=parent_header,
                    content={
                        "ename": type(exception).__name__,
                        "evalue": exception.args[0],
                        "traceback": traceback,
                    },
                )
                to_send = serialize(msg, self.key)
                await self.from_iopub_send_stream.send(to_send)
            else:
                status = "ok"
        msg = self.create_message(
            "execute_reply",
            parent_header=parent_header,
            content={"status": status, "execution_count": execution_count},
            address=idents[0],
        )
        to_send = serialize(msg, self.key)
        await self.from_shell_send_stream.send(to_send)
        self.execution_state = "idle"
        msg = self.create_message(
            "status",
            parent_header=parent_header,
            content={"execution_state": self.execution_state},
        )
        to_send = serialize(msg, self.key)
        await self.from_iopub_send_stream.send(to_send)

    def task(self, cell_i: int = -1) -> Awaitable:
        if cell_i < 0:
            i = self.task_i - 1 + cell_i
        else:
            i = cell_i
        if i in self.running_cells:
            return self.running_cells[i]
        return asyncio.sleep(0)

    async def ainput(self, prompt: str = "") -> Any:
        parent = PARENT_VAR.get()
        idents = IDENTS_VAR.get()
        if parent["content"]["allow_stdin"]:
            msg = self.create_message(
                "input_request",
                parent_header=parent["header"],
                content={"prompt": prompt, "password": False},
                address=idents[0],
            )
            to_send = serialize(msg, self.key)
            await self.from_stdin_send_stream.send(to_send)
            msg_list = await self.to_stdin_receive_stream.receive()
            idents, msg_list = feed_identities(msg_list)
            msg = deserialize(msg_list)
            idents, msg = res
            if msg["content"]["status"] == "ok":
                return msg["content"]["value"]

    def print(
        self,
        *objects,
        sep: str = " ",
        end: str = "\n",
        file=sys.stdout,
        flush: bool = False,
    ) -> None:
        if file is sys.stdout:
            name = "stdout"
        elif file is sys.stderr:
            name = "stderr"
        else:
            print(*objects, sep, end, file, flush)
            return
        f = StringIO()
        print(*objects, sep=sep, end=end, file=f, flush=True)
        text = f.getvalue()
        f.close()
        msg = self.create_message(
            "stream",
            parent_header=PARENT_VAR.get()["header"],
            content={"name": name, "text": text},
        )
        to_send = serialize(msg, self.key)
        self.from_iopub_send_stream.send_nowait(to_send)

    def create_message(
        self,
        msg_type: str,
        content: Dict = {},
        parent_header: Dict[str, Any] = {},
        address: bytes | None = None,
    ) -> Dict[str, Any]:
        msg = create_message(
            msg_type,
            content=content,
            parent_header=parent_header,
            msg_cnt=self.msg_cnt,
            address=address,
        )
        self.msg_cnt += 1
        return msg

    async def show_result(self, result, globals_, parent_header):
        if result is not None:
            globals_["_"] = result
            send_stream = True
            if getattr(result, "_repr_mimebundle_", None) is not None:
                try:
                    data = result._repr_mimebundle_()
                    display.display(data, raw=True)
                    send_stream = False
                except Exception:
                    pass
            elif getattr(result, "_ipython_display_", None) is not None:
                try:
                    result._ipython_display_()
                    send_stream = False
                except Exception:
                    pass
            if send_stream:
                msg = self.create_message(
                    "stream",
                    parent_header=parent_header,
                    content={"name": "stdout", "text": f"{repr(result)}\n"},
                )
                to_send = serialize(msg, self.key)
                await self.from_iopub_send_stream.send(to_send)
