import sys
import platform
import asyncio
import json
import traceback
import ast
from io import StringIO
from typing import List, Tuple, Dict, Any, Optional, cast

from zmq.sugar.socket import Socket

from .connect import connect_channel
from .message import send_message, create_message, deserialize
from ._version import __version__


DELIM = b"<IDS|MSG>"


def __print__(kernel):
    def new_print(
        *objects, sep=" ", end="\n", file=sys.stdout, flush=False, parent_header=""
    ):
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
        msg = create_message(
            "stream",
            parent_header=parent_header,
            content={"name": name, "text": text},
        )
        send_message(msg, kernel.iopub_channel, kernel.key)

    return new_print


async def check_message(sock: Socket) -> bool:
    return await sock.poll(0)


async def receive_message(
    sock: Socket, timeout: float = float("inf")
) -> Optional[Dict[str, Any]]:
    timeout *= 1000  # in ms
    ready = await sock.poll(timeout)
    if ready:
        msg_list = await sock.recv_multipart()
        idents, msg_list = feed_identities(msg_list)
        return idents, deserialize(msg_list)
    return None


def feed_identities(msg_list: List[bytes]) -> Tuple[List[bytes], List[bytes]]:
    idx = msg_list.index(DELIM)
    return msg_list[:idx], msg_list[idx + 1 :]  # noqa


def make_async(code: str, globals_: Dict[str, Any]) -> str:
    async_code = ["async def __async_cell__(__parent_header__):"]
    if globals_:
        async_code += ["    global " + ", ".join(globals_.keys())]
    async_code += [
        "    def print(*objects, sep=' ', end='\\n', file=sys.stdout, flush=False):"
    ]
    async_code += [
        "        __print__(*objects, sep=sep, end=end, file=file, flush=flush, "
        "parent_header=__parent_header__)"
    ]
    async_code += ["    __result__ = None"]
    async_code += ["    __exception__ = None"]
    async_code += ["    __interrupted__ = False"]
    async_code += ["    try:"]
    code_lines = code.splitlines()
    async_code += ["        " + line for line in code_lines[:-1]]
    last_line = code_lines[-1]
    return_value = False
    if not last_line.startswith((" ", "\t")):
        try:
            n = ast.parse(last_line)
        except Exception:
            pass
        else:
            if type(n.body[0]) is ast.Expr:
                return_value = True
    if return_value:
        async_code += ["        __result__ = " + last_line]
    else:
        async_code += ["        " + last_line]
    async_code += ["    except asyncio.CancelledError:"]
    async_code += ["        __exception__ = RuntimeError('Kernel interrupted')"]
    async_code += ["    except KeyboardInterrupt:"]
    async_code += ["        __exception__ = RuntimeError('Kernel interrupted')"]
    async_code += ["        __interrupted__ = True"]
    async_code += ["    except Exception as e:"]
    async_code += ["        __exception__ = e"]
    async_code += ["    __globals__.update(locals())"]
    async_code += ["    __globals__.update(globals())"]
    async_code += ["    del __globals__['print']"]
    async_code += ["    del __globals__['__parent_header__']"]
    async_code += ["    del __globals__['__result__']"]
    async_code += ["    del __globals__['__exception__']"]
    async_code += ["    if __exception__ is None:"]
    async_code += ["        return __result__"]
    async_code += ["    raise __exception__"]
    return "\n".join(async_code)


class Kernel:
    def __init__(
        self,
        kernel_name: str,
        connection_file: str,
    ):
        self.loop = asyncio.get_event_loop()
        self.kernel_name = kernel_name
        self.running_cells = {}
        self.task_i = 0
        self.execution_count = 1
        self.execution_state = "starting"
        self.globals = {"__interrupted__": False}
        self.global_context = {
            "asyncio": asyncio,
            "sys": sys,
            "__print__": __print__(self),
            "__globals__": self.globals,
        }
        self.local_context = {}
        with open(connection_file) as f:
            self.connection_cfg = json.load(f)
        self.key = cast(str, self.connection_cfg["key"])
        init = True
        while True:
            try:
                self.loop.run_until_complete(self.main(init))
            except KeyboardInterrupt:
                for task in self.running_cells.values():
                    task.cancel()
                self.running_cells = {}
            else:
                if not self.restart:
                    break
            finally:
                init = False

    async def main(self, init):
        if init:
            self.shell_channel = connect_channel("shell", self.connection_cfg)
            self.iopub_channel = connect_channel("iopub", self.connection_cfg)
            self.control_channel = connect_channel("control", self.connection_cfg)
            msg = create_message(
                "status", content={"execution_state": self.execution_state}
            )
            send_message(msg, self.iopub_channel, self.key)
            self.execution_state = "idle"
            self.stop = asyncio.Event()
            asyncio.create_task(self.listen_shell())
            asyncio.create_task(self.listen_control())
        while True:
            await self.stop.wait()
            if self.restart:
                self.stop.clear()
            else:
                break

    async def listen_shell(self):
        while True:
            if self.globals["__interrupted__"] and not await check_message(
                self.shell_channel
            ):
                self.globals["__interrupted__"] = False
            idents, msg = await receive_message(self.shell_channel)
            msg_type = msg["header"]["msg_type"]
            parent_header = msg["header"]
            if msg_type == "kernel_info_request":
                msg = create_message(
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
                msg = create_message(
                    "status",
                    parent_header=parent_header,
                    content={"execution_state": self.execution_state},
                )
                send_message(msg, self.iopub_channel, self.key)
            elif msg_type == "execute_request":
                if self.globals["__interrupted__"]:
                    self.finish_execution(idents, parent_header, no_exec=True)
                    continue
                self.execution_state = "busy"
                code = msg["content"]["code"]
                msg = create_message(
                    "status",
                    parent_header=parent_header,
                    content={"execution_state": self.execution_state},
                )
                send_message(msg, self.iopub_channel, self.key)
                async_code = make_async(code, self.globals)
                try:
                    exec(async_code, self.global_context, self.local_context)
                except Exception as e:
                    self.finish_execution(idents, parent_header, exception=e)
                else:
                    task = asyncio.create_task(
                        self.execute_code(idents, parent_header, self.task_i)
                    )
                    self.running_cells[self.task_i] = task
                    self.task_i += 1

    async def listen_control(self):
        while True:
            idents, msg = await receive_message(self.control_channel)
            msg_type = msg["header"]["msg_type"]
            parent_header = msg["header"]
            if msg_type == "shutdown_request":
                self.restart = msg["content"]["restart"]
                msg = create_message(
                    "shutdown_reply",
                    parent_header=parent_header,
                    content={"restart": self.restart},
                )
                send_message(msg, self.control_channel, self.key, idents[0])
                if self.restart:
                    self.globals = {}
                    self.global_context = {
                        "asyncio": asyncio,
                        "sys": sys,
                        "__print__": __print__(self),
                        "__globals__": self.globals,
                    }
                    self.local_context = {}
                    self.execution_count = 1
                self.stop.set()

    async def execute_code(self, idents, parent_header, task_i):
        exception = None
        try:
            result = await self.local_context["__async_cell__"](parent_header)
        except Exception as e:
            exception = e
            if self.globals["__interrupted__"]:
                for task in self.running_cells.values():
                    task.cancel()
                self.running_cells = {}
        else:
            if result is not None:
                msg = create_message(
                    "stream",
                    parent_header=parent_header,
                    content={"name": "stdout", "text": f"{repr(result)}\n"},
                )
                send_message(msg, self.iopub_channel, self.key)
        finally:
            self.global_context.update(self.globals)
            self.finish_execution(idents, parent_header, exception=exception)
            if task_i in self.running_cells:
                del self.running_cells[task_i]

    def finish_execution(self, idents, parent_header, exception=None, no_exec=False):
        execution_count = self.execution_count
        if no_exec:
            status = "ok"
            execution_count = None
        else:
            self.execution_count += 1
            if exception is None:
                status = "ok"
            else:
                status = "error"
                tb = "".join(traceback.format_tb(exception.__traceback__))
                msg = create_message(
                    "stream",
                    parent_header=parent_header,
                    content={"name": "stderr", "text": f"{tb}{exception}\n"},
                )
                send_message(msg, self.iopub_channel, self.key)
        msg = create_message(
            "execute_reply",
            parent_header=parent_header,
            content={"status": status, "execution_count": execution_count},
        )
        send_message(msg, self.shell_channel, self.key, idents[0])
        self.execution_state = "idle"
        msg = create_message(
            "status",
            parent_header=parent_header,
            content={"execution_state": self.execution_state},
        )
        send_message(msg, self.iopub_channel, self.key)
