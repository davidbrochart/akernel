import platform
import sys
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from functools import partial
from io import StringIO
from types import TracebackType
from typing import Any

import comm  # type: ignore
from anyio import (
    CancelScope,
    Event,
    RunFinishedError,
    TaskHandle,
    create_memory_object_stream,
    create_task_group,
    from_thread,
    get_cancelled_exc_class,
    run,
    to_thread,
)
from anyio.lowlevel import EventLoopToken, checkpoint, current_token

import akernel.IPython
from akernel.comm.manager import CommManager
from akernel.display import display
from akernel.IPython import core

from . import __version__
from .execution import compile_cell, execute_cell
from .message import (
    create_message,
    deserialize,
    feed_identities,
    protocol_version,
    serialize,
)
from .traceback import get_traceback

ThreadResult = tuple[Any, BaseException | None, TracebackType | None]
WorkerCommand = tuple[EventLoopToken, Callable[..., Any], tuple[Any, ...]]

PARENT_VAR: ContextVar = ContextVar("parent")
IDENTS_VAR: ContextVar = ContextVar("idents")


@dataclass
class ThreadExecution:
    task_i: int
    parent: dict
    idents: list[bytes]
    async_cell: Any
    reply_stream: Any
    # Owned by the server event loop; worker access goes through from_thread.
    _cancelled: bool = False
    started: bool = False
    cancel_scope: CancelScope | None = None

    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True

    def start(self) -> bool:
        if self._cancelled:
            return False
        self.started = True
        return True


KERNEL: "Kernel"


sys.modules["IPython.display"] = display
sys.modules["IPython"] = akernel.IPython
sys.modules["IPython.core"] = core


class Kernel:
    stop_event: Event
    restart: bool
    key: str
    comm_manager: CommManager
    cell_done: dict[int, Event]
    running_cells: dict[int, TaskHandle]
    _source_map: dict[str, str]
    task_i: int
    execution_count: int
    execution_state: str
    globals: dict[str, Any]
    kernel_initialized: bool

    def __init__(
        self,
        to_shell_receive_stream,
        from_shell_send_stream,
        to_control_receive_stream,
        from_control_send_stream,
        to_stdin_receive_stream,
        from_stdin_send_stream,
        from_iopub_send_stream,
        execute_in_thread: bool = False,
        drain_shell: Callable[[], None] | None = None,
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

        self.execute_in_thread = execute_in_thread
        self._drain_shell = drain_shell
        self.kernel_initialized = False
        self.globals = {}
        self._source_map = {}
        self.cell_done = {}
        self.running_cells = {}
        self.task_i = 0
        self.execution_count = 1
        self.execution_state = "starting"
        self.restart = False
        self.interrupted = False
        self._signal_interrupt_pending = False
        self._interrupt_pending = 0
        self._interrupt_generation = 0
        self._pending_shell_requests: dict[str, bool] = {}
        self.msg_cnt = 0
        self.stop_event = Event()
        self._stopping = False
        self._thread_token: EventLoopToken | None = None
        self._thread_jobs: dict[int, ThreadExecution] = {}
        self._cancelled_cells: set[int] = set()
        self._finishing_cells: dict[int, CancelScope] = {}
        self.key = "0"

    def init_kernel(self):
        if self.kernel_initialized:
            return
        self.globals = {"print": self.print, "_": None}
        if self.execute_in_thread:
            self.globals["input"] = self.input
        else:
            self.globals["ainput"] = self.ainput
        self.kernel_initialized = True

    def request_interrupt(self) -> None:
        """Flag a signal interrupt without touching event-loop state."""
        self._signal_interrupt_pending = True

    def process_pending_interrupt(self) -> None:
        if self._signal_interrupt_pending:
            self.interrupt()

    def interrupt(self):
        """Cancel active and already queued executions without affecting later requests."""
        self._signal_interrupt_pending = False
        if self._drain_shell is not None and not self._stopping:
            self._drain_shell()
        for msg_id in self._pending_shell_requests:
            self._pending_shell_requests[msg_id] = True
        self.interrupted = True
        self._interrupt_generation += 1
        stats = self.to_shell_receive_stream.statistics()
        self._interrupt_pending = stats.current_buffer_used + stats.tasks_waiting_send
        for job in list(self._thread_jobs.values()):
            self.cancel_thread_execution(job)
        for task_i, task in self.running_cells.items():
            self._cancelled_cells.add(task_i)
            if self.execute_in_thread and not self._stopping:
                # Keep waiting for the worker: requesting cancellation does not
                # mean blocking user code has actually stopped.
                continue
            else:
                task.cancel()

    def register_shell_request(self, frames: list[bytes]) -> None:
        # Track transport requests until dispatch, including messages handed
        # directly to a waiting receiver (not counted in stream statistics).
        message = deserialize(feed_identities(frames)[1])
        self._pending_shell_requests[message["header"]["msg_id"]] = False

    def cancel_thread_execution(self, job: ThreadExecution) -> None:
        if job.cancelled():
            return
        job.cancel()
        if self._thread_token is not None and job.cancel_scope is not None:
            self.send_worker_command(job.cancel_scope.cancel)

    def send_worker_command(self, func: Callable[..., Any], *args: Any) -> None:
        token = self._thread_token
        assert token is not None
        self._worker_commands_send.send_nowait((token, func, args))

    async def forward_worker_commands(self) -> None:
        # Cross-thread calls wait for the worker loop. Run them off the server
        # thread and preserve their order, including the shutdown sentinel.
        with CancelScope(shield=True):
            async with self._worker_commands_receive:
                async for token, func, args in self._worker_commands_receive:
                    try:
                        await to_thread.run_sync(
                            partial(from_thread.run_sync, func, *args, token=token)
                        )
                    except RunFinishedError:
                        if not self._stopping:
                            raise

    def deliver_thread_result(self, job, result, exception, traceback) -> None:
        self._thread_jobs.pop(job.task_i, None)
        try:
            if not self._stopping:
                job.reply_stream.send_nowait((result, exception, traceback))
        finally:
            job.reply_stream.close()

    async def thread_execute(self):
        while True:
            job = await self._thread_receive.receive()
            if job is None:
                return

            PARENT_VAR.set(job.parent)
            IDENTS_VAR.set(job.idents)
            result = None
            exception = None
            traceback = None
            with CancelScope() as scope:
                job.cancel_scope = scope
                if from_thread.run_sync(job.start):
                    try:
                        result = await job.async_cell()
                    except get_cancelled_exc_class() as exc:
                        exception = KeyboardInterrupt()
                        traceback = exc.__traceback__
                    except (Exception, KeyboardInterrupt) as exc:  # noqa: BLE001 - report user errors
                        exception = exc
                        traceback = exc.__traceback__
                else:
                    # Cancellation was requested before this job began.
                    exception = KeyboardInterrupt()
            from_thread.run_sync(self.deliver_thread_result, job, result, exception, traceback)

    def _is_stopping(self) -> bool:
        return self._stopping

    async def thread_main(self) -> None:
        self._thread_token = current_token()
        self._thread_send, self._thread_receive = create_memory_object_stream[
            ThreadExecution | None
        ](float("inf"))
        from_thread.run_sync(self._thread_ready.set)
        try:
            async with self._thread_send, self._thread_receive:
                if not from_thread.run_sync(self._is_stopping):
                    await self.thread_execute()
        finally:
            self._thread_token = None

    def run_thread(self) -> None:
        run(self.thread_main)

    async def start(self) -> None:
        async with create_task_group() as self.task_group:
            self._stopping = False
            try:
                if self.execute_in_thread:
                    self._worker_commands_send, self._worker_commands_receive = (
                        create_memory_object_stream[WorkerCommand](float("inf"))
                    )
                    self.task_group.start_soon(self.forward_worker_commands)
                    self._thread_ready = Event()
                    self.task_group.start_soon(to_thread.run_sync, self.run_thread)
                    await self._thread_ready.wait()
                msg = self.create_message(
                    "status", content={"execution_state": self.execution_state}
                )
                to_send = serialize(msg, self.key)
                await self.from_iopub_send_stream.send(to_send)
                self.execution_state = "idle"
                await self.publish_status("idle")
                while True:
                    await self._start()
                    if not self.restart:
                        break
            finally:
                self._stopping = True
                try:
                    self.interrupt()
                    for scope in list(self._finishing_cells.values()):
                        scope.cancel()
                    if self._thread_token is not None:
                        self.send_worker_command(self._thread_send.send_nowait, None)
                finally:
                    if self.execute_in_thread:
                        self._worker_commands_send.close()
                    self.task_group.cancel_scope.cancel()

    async def _start(self) -> None:
        self.task_group.start_soon(self.listen_shell)
        self.task_group.start_soon(self.listen_control)
        while True:
            # run until shutdown request
            await self.stop_event.wait()
            if self.restart:
                self.stop_event = Event()
            else:
                break

    async def listen_shell(self) -> None:
        while True:
            # Give cell execution a scheduling opportunity.
            await checkpoint()
            msg_list = await self.to_shell_receive_stream.receive()
            self.process_pending_interrupt()
            # Only discard requests that were queued when interrupt() ran.
            interrupt_generation = self._interrupt_generation
            interrupted = self._interrupt_pending > 0
            if interrupted:
                self._interrupt_pending -= 1
            idents, msg_list = feed_identities(msg_list)
            msg = deserialize(msg_list)
            msg_type = msg["header"]["msg_type"]
            parent_header = msg["header"]
            interrupted |= self._pending_shell_requests.pop(parent_header["msg_id"], False)
            parent = msg
            if msg_type == "kernel_info_request":
                await self.publish_status("busy", parent_header)
                msg = self.create_message(
                    "kernel_info_reply",
                    parent_header=parent_header,
                    content={
                        "status": "ok",
                        "protocol_version": protocol_version,
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
                await self.publish_status("idle", parent_header)
            elif msg_type == "history_request":
                await self.publish_status("busy", parent_header)
                # Execution history is not retained by this kernel.
                reply = self.create_message(
                    "history_reply",
                    parent_header=parent_header,
                    content={"status": "ok", "history": []},
                    address=idents[0],
                )
                await self.from_shell_send_stream.send(serialize(reply, self.key))
                await self.publish_status("idle", parent_header)
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
                if interrupted or interrupt_generation != self._interrupt_generation:
                    await self.finish_execution(idents, parent_header, None, no_exec=True)
                    continue
                task = self.task_group.create_task(
                    self.execute_and_finish(idents, parent, self.task_i, code)
                )
                self.cell_done[self.task_i] = Event()
                self.running_cells[self.task_i] = task
                self.task_i += 1
            elif msg_type == "comm_info_request":
                self.execution_state = "busy"
                msg2 = self.create_message(
                    "status",
                    parent_header=parent_header,
                    content={"execution_state": self.execution_state},
                )
                to_send = serialize(msg2, self.key)
                await self.from_iopub_send_stream.send(to_send)
                target_name = msg["content"].get("target_name")
                comms = {
                    comm_id: {"target_name": comm.target_name}
                    for comm_id, comm in self.comm_manager.comms.items()
                    if target_name is None or comm.target_name == target_name
                }
                msg2 = self.create_message(
                    "comm_info_reply",
                    parent_header=parent_header,
                    content={"status": "ok", "comms": comms},
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

    async def publish_status(self, state: str, parent_header: dict[str, Any] | None = None) -> None:
        msg = self.create_message(
            "status", parent_header=parent_header, content={"execution_state": state}
        )
        await self.from_iopub_send_stream.send(serialize(msg, self.key))

    async def listen_control(self) -> None:
        while True:
            msg_list = await self.to_control_receive_stream.receive()
            idents, msg_list = feed_identities(msg_list)
            msg = deserialize(msg_list)
            msg_type = msg["header"]["msg_type"]
            parent_header = msg["header"]
            if msg_type == "interrupt_request":
                self.interrupt()
                reply = self.create_message(
                    "interrupt_reply",
                    parent_header=parent_header,
                    content={"status": "ok"},
                    address=idents[0],
                )
                await self.from_control_send_stream.send(serialize(reply, self.key))
            elif msg_type == "shutdown_request":
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
        idents: list[bytes],
        parent: dict[str, Any],
        task_i: int,
        code: str,
    ) -> None:
        parent_header = parent["header"]
        PARENT_VAR.set(parent)
        IDENTS_VAR.set(idents)
        traceback, exception = [], None
        execution_count = 0
        job = None
        started = False
        aborted = False

        async def begin_execution():
            nonlocal execution_count
            execution_count = self.execution_count
            self.execution_count += 1
            self._source_map[f"<cell-{execution_count - 1}>"] = code
            message = self.create_message(
                "execute_input",
                parent_header=parent_header,
                content={"code": code, "execution_count": execution_count},
            )
            await self.from_iopub_send_stream.send(serialize(message, self.key))

        async def run_cell():
            # Publish the number only when this execution gets its turn, and
            # (in thread mode) after the worker has accepted the job.
            if self.execute_in_thread:
                from_thread.run(begin_execution)
            else:
                await begin_execution()
            cell = compile_cell(code, execution_count - 1)
            return await execute_cell(cell, self.globals)

        try:
            prev_task_i = task_i - 1
            if prev_task_i in self.cell_done:
                await self.cell_done[prev_task_i].wait()
                self.cell_done.pop(prev_task_i, None)
            self.process_pending_interrupt()
            if task_i in self._cancelled_cells:
                raise KeyboardInterrupt()
            self.init_kernel()
            if self.execute_in_thread:
                send_stream, receive_stream = create_memory_object_stream[ThreadResult](1)
                job = ThreadExecution(
                    task_i,
                    parent,
                    idents,
                    run_cell,
                    send_stream,
                )
                self._thread_jobs[task_i] = job
                self.send_worker_command(self._thread_send.send_nowait, job)
                try:
                    result, exception, worker_traceback = await receive_stream.receive()
                finally:
                    receive_stream.close()
                aborted = not job.started
                if exception is not None and not aborted:
                    traceback = get_traceback(
                        code, exception, worker_traceback, execution_count, self._source_map
                    )
            else:
                started = True
                result = await run_cell()
            if exception is None:
                await self.show_result(result, self.globals, parent_header)
        except (get_cancelled_exc_class(), KeyboardInterrupt) as exc:
            if job is not None:
                self.cancel_thread_execution(job)
            aborted = not (job.started if job is not None else started)
            if not aborted:
                exception = KeyboardInterrupt()
                traceback = get_traceback(
                    code, exception, exc.__traceback__, execution_count, self._source_map
                )
        except Exception as exc:  # noqa: BLE001 - report user errors without stopping the kernel
            exception = exc
            traceback = get_traceback(
                code, exc, exc.__traceback__, execution_count, self._source_map
            )
        finally:
            # A synchronous cell can finish before the signal reader resumes.
            # Cancel its queued successors before releasing their execution gate.
            self.process_pending_interrupt()
            self.cell_done[task_i].set()
            try:
                if not self._stopping:
                    # TaskHandle.cancel() uses level cancellation: the final
                    # reply must be shielded so the frontend can finish the cell.
                    with CancelScope(shield=True) as scope:
                        self._finishing_cells[task_i] = scope
                        await self.finish_execution(
                            idents,
                            parent_header,
                            None if aborted else execution_count,
                            no_exec=aborted,
                            exception=exception,
                            traceback=traceback,
                        )
            finally:
                self._finishing_cells.pop(task_i, None)
                self._cancelled_cells.discard(task_i)
                self.running_cells.pop(task_i, None)

    async def finish_execution(
        self,
        idents: list[bytes],
        parent_header: dict[str, Any],
        execution_count: int | None,
        exception: BaseException | None = None,
        no_exec: bool = False,
        traceback: list[str] | None = None,
    ) -> None:
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
                        "evalue": str(exception),
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

    def input(self, prompt: str = "") -> Any:
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
            from_thread.run_sync(self.from_stdin_send_stream.send_nowait, to_send)
            msg_list = from_thread.run(self.to_stdin_receive_stream.receive)
            idents, msg_list = feed_identities(msg_list)
            msg = deserialize(msg_list)
            if msg["content"]["status"] == "ok":
                return msg["content"]["value"]

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
            self.from_stdin_send_stream.send_nowait(to_send)
            msg_list = await self.to_stdin_receive_stream.receive()
            idents, msg_list = feed_identities(msg_list)
            msg = deserialize(msg_list)
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
        if self.execute_in_thread:
            from_thread.run_sync(self.from_iopub_send_stream.send_nowait, to_send)
        else:
            self.from_iopub_send_stream.send_nowait(to_send)

    def create_message(
        self,
        msg_type: str,
        content: dict | None = None,
        parent_header: dict[str, Any] | None = None,
        address: bytes | None = None,
    ) -> dict[str, Any]:
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
                except Exception:  # noqa: BLE001, S110 - fall back to repr if rich display fails
                    pass
            elif getattr(result, "_ipython_display_", None) is not None:
                try:
                    result._ipython_display_()
                    send_stream = False
                except Exception:  # noqa: BLE001, S110 - fall back to repr if rich display fails
                    pass
            if send_stream:
                msg = self.create_message(
                    "stream",
                    parent_header=parent_header,
                    content={"name": "stdout", "text": f"{result!r}\n"},
                )
                to_send = serialize(msg, self.key)
                await self.from_iopub_send_stream.send(to_send)
