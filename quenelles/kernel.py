import sys
import signal
import asyncio
import json

from rich.live import Live
from rich.tree import Tree
from rich.status import Status

from .connect import connect_channel


def signal_handler(sig, frame):
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)


class Kernel:
    def __init__(self, kernel_name: str, connection_file: str, log: bool = True):
        self.log = log
        with open(connection_file) as f:
            self.connection_cfg = json.load(f)
        asyncio.run(self.main())

    async def main(self):
        self.shell_channel = connect_channel("shell", self.connection_cfg)
        self.iopub_channel = connect_channel("iopub", self.connection_cfg)
        if self.log:
            status0 = Status("Running")
            tree0 = Tree(status0)  # type: ignore
            live = Live(tree0, refresh_per_second=10)
            live.start()
        await self.shell_channel.poll()
        if self.log:
            status1 = Status("Received message on shell channel")
            tree0.add(status1)  # type: ignore
