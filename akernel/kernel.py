import sys
import platform
import asyncio
import json
from io import StringIO
from contextvars import ContextVar
from typing import Dict, Any, List, Optional, Union, Awaitable, cast

from zmq.sugar.socket import Socket

from akernel.comm import comm
from akernel.comm.manager import CommManager
from akernel.display import display
import akernel.IPython
from akernel.IPython import core
from .connect import connect_channel
from .message import receive_message, send_message, create_message, check_message
from .execution import pre_execute
from .traceback import get_traceback
from . import __version__


PARENT_HEADER_VAR: ContextVar = ContextVar("parent_header")

KERNEL: "Kernel"


sys.modules["ipykernel.comm"] = comm
sys.modules["IPython.display"] = display
sys.modules["IPython"] = akernel.IPython
sys.modules["IPython.core"] = core


class Kernel:

    shell_channel: Socket
    iopub_channel: Socket
    control_channel: Socket
    connection_cfg: Dict[str, Union[str, int]]
    stop: asyncio.Event
    restart: bool
    key: str
    comm_manager: CommManager
    kernel_mode: str
    running_cells: Dict[int, asyncio.Task]
    task_i: int
    execution_count: int
    execution_state: str
    globals: Dict[str, Any]
    locals: Dict[str, Any]

    def __init__(
        self,
        kernel_mode: str,
        connection_file: str,
    ):
        global KERNEL
        KERNEL = self
        self.comm_manager = CommManager()
        self.loop = asyncio.get_event_loop()
        self.kernel_mode = kernel_mode
        self.running_cells = {}
        self.task_i = 0
        self.execution_count = 1
        self.execution_state = "starting"
        self.globals = {
            "asyncio": asyncio,
            "print": self.print,
            "__task__": self.task,
            "_": None,
        }
        self.locals = {}
        if kernel_mode == "react":
            code = "import ipyx; globals()['ipyx'] = ipyx"
            exec(code, self.globals, self.locals)
        with open(connection_file) as f:
            self.connection_cfg = json.load(f)
        self.key = cast(str, self.connection_cfg["key"])
        self.restart = False
        self.interrupted = False
        self.msg_cnt = 0
        self.shell_channel = connect_channel("shell", self.connection_cfg)
        self.iopub_channel = connect_channel("iopub", self.connection_cfg)
        self.control_channel = connect_channel("control", self.connection_cfg)
        msg = self.create_message(
            "status", content={"execution_state": self.execution_state}
        )
        send_message(msg, self.iopub_channel, self.key)
        self.execution_state = "idle"
        self.stop = asyncio.Event()
        while True:
            try:
                self.loop.run_until_complete(self.main())
            except KeyboardInterrupt:
                self.interrupt()
            else:
                if not self.restart:
                    break
            finally:
                self.shell_task.cancel()
                self.control_task.cancel()

    def interrupt(self):
        self.interrupted = True
        for task in self.running_cells.values():
            task.cancel()
        self.running_cells = {}

    async def main(self) -> None:
        self.shell_task = asyncio.create_task(self.listen_shell())
        self.control_task = asyncio.create_task(self.listen_control())
        while True:
            # run until shutdown request
            await self.stop.wait()
            if self.restart:
                # kernel restart
                self.stop.clear()
            else:
                # kernel shutdown
                break

    async def listen_shell(self) -> None:
        while True:
            # let a chance to execute a blocking cell
            await asyncio.sleep(0)
            # if there was a blocking cell execution, and it was interrupted,
            # let's ignore all the following execution requests until the pipe
            # is empty
            if self.interrupted and not await check_message(self.shell_channel):
                self.interrupted = False
            res = await receive_message(self.shell_channel)
            assert res is not None
            idents, msg = res
            msg_type = msg["header"]["msg_type"]
            parent_header = msg["header"]
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
                )
                send_message(msg, self.shell_channel, self.key, idents[0])
                msg = self.create_message(
                    "status",
                    parent_header=parent_header,
                    content={"execution_state": self.execution_state},
                )
                send_message(msg, self.iopub_channel, self.key)
            elif msg_type == "execute_request":
                self.execution_state = "busy"
                code = msg["content"]["code"]
                msg = self.create_message(
                    "status",
                    parent_header=parent_header,
                    content={"execution_state": self.execution_state},
                )
                send_message(msg, self.iopub_channel, self.key)
                if self.interrupted:
                    self.finish_execution(idents, parent_header, None, no_exec=True)
                    continue
                msg = self.create_message(
                    "execute_input",
                    parent_header=parent_header,
                    content={"code": code, "execution_count": self.execution_count},
                )
                send_message(msg, self.iopub_channel, self.key)
                react = self.kernel_mode == "react"
                traceback, exception = pre_execute(
                    code, self.globals, self.locals, self.execution_count, react=react
                )
                if traceback:
                    self.finish_execution(
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
                            parent_header,
                            self.task_i,
                            self.execution_count,
                            code,
                        )
                    )
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
                send_message(msg2, self.iopub_channel, self.key)
                if "target_name" in msg["content"]:
                    target_name = msg["content"]["target_name"]
                    comms: List[str] = []
                    msg2 = self.create_message(
                        "comm_info_reply",
                        parent_header=parent_header,
                        content={
                            "status": "ok",
                            "comms": {
                                comm_id: {"target_name": target_name}
                                for comm_id in comms
                            },
                        },
                    )
                    send_message(msg2, self.shell_channel, self.key, idents[0])
                self.execution_state = "idle"
                msg2 = self.create_message(
                    "status",
                    parent_header=parent_header,
                    content={"execution_state": self.execution_state},
                )
                send_message(msg2, self.iopub_channel, self.key)
            elif msg_type == "comm_msg":
                self.comm_manager.comm_msg(None, None, msg)

    async def listen_control(self) -> None:
        while True:
            res = await receive_message(self.control_channel)
            assert res is not None
            idents, msg = res
            msg_type = msg["header"]["msg_type"]
            parent_header = msg["header"]
            if msg_type == "shutdown_request":
                self.restart = msg["content"]["restart"]
                msg = self.create_message(
                    "shutdown_reply",
                    parent_header=parent_header,
                    content={"restart": self.restart},
                )
                send_message(msg, self.control_channel, self.key, idents[0])
                if self.restart:
                    self.globals = {
                        "asyncio": asyncio,
                        "print": self.print,
                        "__task__": self.task,
                        "_": None,
                    }
                    self.locals = {}
                    if self.kernel_mode == "react":
                        code = "import ipyx; globals()['ipyx'] = ipyx"
                        exec(code, self.globals, self.locals)
                    self.execution_count = 1
                self.stop.set()

    async def execute_and_finish(
        self,
        idents: List[bytes],
        parent_header: Dict[str, Any],
        task_i: int,
        execution_count: int,
        code: str,
    ) -> None:
        PARENT_HEADER_VAR.set(parent_header)
        traceback, exception = [], None
        try:
            result = await self.locals["__async_cell__"]()
        except KeyboardInterrupt:
            self.interrupt()
        except Exception as e:
            exception = e
            traceback = get_traceback(code, e, execution_count)
        else:
            if result is not None:
                self.globals["_"] = result
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
                    send_message(msg, self.iopub_channel, self.key)
        finally:
            self.finish_execution(
                idents,
                parent_header,
                execution_count,
                exception=exception,
                traceback=traceback,
            )
            if task_i in self.running_cells:
                del self.running_cells[task_i]

    def finish_execution(
        self,
        idents: List[bytes],
        parent_header: Dict[str, Any],
        execution_count: Optional[int],
        exception: Optional[Exception] = None,
        no_exec: bool = False,
        traceback: List[str] = [],
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
                        "evalue": exception.args[0],
                        "traceback": traceback,
                    },
                )
                send_message(msg, self.iopub_channel, self.key)
            else:
                status = "ok"
        msg = self.create_message(
            "execute_reply",
            parent_header=parent_header,
            content={"status": status, "execution_count": execution_count},
        )
        send_message(msg, self.shell_channel, self.key, idents[0])
        self.execution_state = "idle"
        msg = self.create_message(
            "status",
            parent_header=parent_header,
            content={"execution_state": self.execution_state},
        )
        send_message(msg, self.iopub_channel, self.key)

    def task(self, cell_i: int = -1) -> Awaitable:
        if cell_i < 0:
            i = self.task_i - 1 + cell_i
        else:
            i = cell_i
        if i in self.running_cells:
            return self.running_cells[i]
        return asyncio.sleep(0)

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
            parent_header=PARENT_HEADER_VAR.get(),
            content={"name": name, "text": text},
        )
        send_message(msg, self.iopub_channel, self.key)

    def create_message(
        self,
        msg_type: str,
        content: Dict = {},
        parent_header: Dict[str, Any] = {},
    ) -> Dict[str, Any]:
        msg = create_message(
            msg_type, content=content, parent_header=parent_header, msg_cnt=self.msg_cnt
        )
        self.msg_cnt += 1
        return msg
