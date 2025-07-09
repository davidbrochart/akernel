from __future__ import annotations

from typing import Union

import zmq
from zmq import Context
from zmq_anyio import Socket


context = Context()

cfg_t = dict[str, Union[str, int]]

channel_socket_types = {
    "shell": zmq.ROUTER,
    "control": zmq.ROUTER,
    "iopub": zmq.PUB,
    "stdin": zmq.ROUTER,
}


def create_socket(channel: str, cfg: cfg_t) -> Socket:
    ip = cfg["ip"]
    port = cfg[f"{channel}_port"]
    url = f"tcp://{ip}:{port}"
    socket_type = channel_socket_types[channel]
    sock = Socket(context.socket(socket_type))
    sock.linger = 1000
    sock.bind(url)
    return sock


def connect_channel(channel_name: str, cfg: cfg_t) -> Socket:
    return create_socket(channel_name, cfg)
