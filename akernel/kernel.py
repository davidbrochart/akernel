import sys
import signal
import asyncio
import json
from typing import List, Tuple, Dict, Any, Optional, cast

from zmq.sugar.socket import Socket

from .connect import connect_channel
from .message import send_message, create_message, deserialize


DELIM = b"<IDS|MSG>"


def signal_handler(sig, frame):
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)


class Stream:
    def __init__(self, kernel, stream_name):
        self.kernel = kernel
        self.stream_name = stream_name
        self.text = []

    def write(self, text):
        self.text.append(text)
        if text.endswith("\n"):
            text = "".join(self.text)
            self.text = []
            msg = create_message(
                "stream",
                parent_header=self.kernel.parent_header,
                content={"name": self.stream_name, "text": text},
            )
            send_message(msg, self.kernel.iopub_channel, self.kernel.key)

    def flush(self):
        pass


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


def make_async(code: str, globals_: List[str]) -> str:
    async_code = ["async def async_func():"]
    if globals_:
        async_code += ["    global " + ", ".join(globals_)]
    async_code += ["    " + line for line in code.splitlines()]
    async_code += ["    __globals__.update(locals())"]
    async_code += ["    __globals__.update(globals())"]
    return "\n".join(async_code)


class Kernel:
    def __init__(
        self,
        kernel_name: str,
        connection_file: str,
    ):
        self.kernel_name = kernel_name
        self.globals = {}
        self.global_context = {
            "asyncio": asyncio,
            "__streamout__": Stream(self, "stdout"),
            "__streamerr__": Stream(self, "stderr"),
            "__globals__": self.globals,
        }
        self.local_context = {}
        self.parent_header = {}
        code = "import sys;sys.stdout=__streamout__;sys.stderr=__streamerr__"
        exec(code, self.global_context, self.local_context)
        with open(connection_file) as f:
            self.connection_cfg = json.load(f)
        self.key = cast(str, self.connection_cfg["key"])
        asyncio.run(self.main())

    async def main(self):
        self.shell_channel = connect_channel("shell", self.connection_cfg)
        self.iopub_channel = connect_channel("iopub", self.connection_cfg)
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
                msg = create_message("status", parent_header=parent_header)
                send_message(msg, self.iopub_channel, self.key)
            elif msg_type == "execute_request":
                code = msg["content"]["code"]
                self.parent_header = parent_header
                async_code = make_async(code, self.globals)
                exec(async_code, self.global_context, self.local_context)
                asyncio.create_task(self.execute_code(idents))

    async def execute_code(self, idents):
        await self.local_context["async_func"]()
        self.global_context.update(self.globals)
        msg = create_message(
            "status",
            parent_header=self.parent_header,
            content={"execution_state": "idle"},
        )
        send_message(msg, self.iopub_channel, self.key)
        msg = create_message("execute_reply", parent_header=self.parent_header)
        send_message(msg, self.shell_channel, self.key, idents[0])
