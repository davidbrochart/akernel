import sys
import signal
import asyncio
import json
import traceback
import ast
from io import StringIO
from typing import List, Tuple, Dict, Any, Optional, cast

from zmq.sugar.socket import Socket

from .connect import connect_channel
from .message import send_message, create_message, deserialize


DELIM = b"<IDS|MSG>"


def signal_handler(sig, frame):
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)


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
    code_lines = code.splitlines()
    async_code += ["    " + line for line in code_lines[:-1]]
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
        async_code += ["    __result__ = " + last_line]
    else:
        async_code += ["    " + last_line]
        async_code += ["    __result__ = None"]
    async_code += ["    __globals__.update(locals())"]
    async_code += ["    __globals__.update(globals())"]
    async_code += ["    del __globals__['print']"]
    async_code += ["    del __globals__['__parent_header__']"]
    async_code += ["    return __result__"]
    return "\n".join(async_code)


class Kernel:
    def __init__(
        self,
        kernel_name: str,
        connection_file: str,
    ):
        self.kernel_name = kernel_name
        self.execution_count = 1
        self.execution_state = "starting"
        self.globals = {}
        self.global_context = {
            "asyncio": asyncio,
            "sys": sys,
            "__print__": __print__(self),
            "__globals__": self.globals,
        }
        self.local_context = {}
        self.parent_header = {}
        with open(connection_file) as f:
            self.connection_cfg = json.load(f)
        self.key = cast(str, self.connection_cfg["key"])
        asyncio.run(self.main())

    async def main(self):
        self.shell_channel = connect_channel("shell", self.connection_cfg)
        self.iopub_channel = connect_channel("iopub", self.connection_cfg)
        msg = create_message(
            "status", content={"execution_state": self.execution_state}
        )
        send_message(msg, self.iopub_channel, self.key)
        self.execution_state = "idle"
        asyncio.create_task(self.listen_shell())
        while True:
            await asyncio.sleep(1)

    async def listen_shell(self):
        while True:
            idents, msg = await receive_message(self.shell_channel)
            msg_type = msg["header"]["msg_type"]
            parent_header = msg["header"]
            if msg_type == "kernel_info_request":
                msg = create_message("kernel_info_reply")
                send_message(msg, self.shell_channel, self.key, idents[0])
                msg = create_message(
                    "status",
                    parent_header=parent_header,
                    content={"execution_state": self.execution_state},
                )
                send_message(msg, self.iopub_channel, self.key)
            elif msg_type == "execute_request":
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
                    asyncio.create_task(self.execute_code(idents, parent_header))

    async def execute_code(self, idents, parent_header):
        exception = None
        try:
            result = await self.local_context["__async_cell__"](parent_header)
        except Exception as e:
            exception = e
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

    def finish_execution(self, idents, parent_header, exception=None):
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
        self.execution_state = "idle"
        msg = create_message(
            "status",
            parent_header=parent_header,
            content={"execution_state": self.execution_state},
        )
        send_message(msg, self.iopub_channel, self.key)
        msg = create_message(
            "execute_reply",
            parent_header=parent_header,
            content={"status": status, "execution_count": self.execution_count},
        )
        send_message(msg, self.shell_channel, self.key, idents[0])
        self.execution_count += 1
