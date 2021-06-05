import zmq
from typing import Dict, Union

import zmq.asyncio
from zmq.sugar.socket import Socket


context = zmq.asyncio.Context()

cfg_t = Dict[str, Union[str, int]]

channel_socket_types = {
    "shell": zmq.ROUTER,
    "control": zmq.ROUTER,
    "iopub": zmq.PUB,
}


def create_socket(channel: str, cfg: cfg_t) -> Socket:
    ip = cfg["ip"]
    port = cfg[f"{channel}_port"]
    url = f"tcp://{ip}:{port}"
    socket_type = channel_socket_types[channel]
    sock = context.socket(socket_type)
    sock.linger = 1000
    sock.bind(url)
    return sock


def connect_channel(channel_name: str, cfg: cfg_t) -> Socket:
    sock = create_socket(channel_name, cfg)
    return sock
