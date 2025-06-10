from __future__ import annotations

import uuid
import hmac
import hashlib
from datetime import datetime, timezone
from typing import List, Tuple, Any, cast

from zmq.utils import jsonapi
from zmq.asyncio import Socket
from dateutil.parser import parse as dateutil_parse  # type: ignore


protocol_version_info = (5, 3)
protocol_version = "%i.%i" % protocol_version_info

DELIM = b"<IDS|MSG>"


def date_to_str(obj: dict[str, Any]):
    if obj is not None and "date" in obj and not isinstance(obj["date"], str):
        obj["date"] = obj["date"].isoformat().replace("+00:00", "Z")
    return obj


def utcnow() -> datetime:
    return datetime.utcnow().replace(tzinfo=timezone.utc)


def feed_identities(msg_list: List[bytes]) -> Tuple[List[bytes], List[bytes]]:
    idx = msg_list.index(DELIM)
    return msg_list[:idx], msg_list[idx + 1 :]  # noqa


def create_message_header(msg_type: str, session_id: str, msg_cnt: int) -> dict[str, Any]:
    if not session_id:
        session_id = msg_id = uuid.uuid4().hex
    else:
        msg_id = f"{session_id}_{msg_cnt}"
    header = {
        "date": utcnow(),
        "msg_id": msg_id,
        "msg_type": msg_type,
        "session": session_id,
        "username": "david",
        "version": protocol_version,
    }
    return header


def create_message(
    msg_type: str,
    content: dict = {},
    metadata: dict[str, Any] | None = None,
    parent_header: dict[str, Any] = {},
    session_id: str = "",
    msg_cnt: int = 0,
) -> dict[str, Any]:
    if parent_header:
        session_id = parent_header["session"]
    header = create_message_header(msg_type, session_id, msg_cnt)
    msg = {
        "header": header,
        "msg_id": header["msg_id"],
        "msg_type": header["msg_type"],
        "parent_header": parent_header,
        "content": content,
        "metadata": metadata,
    }
    return msg


def serialize(msg: dict[str, Any], key: str, address: bytes = b"") -> List[bytes]:
    message = [
        pack(date_to_str(msg["header"])),
        pack(date_to_str(msg["parent_header"])),
        pack(date_to_str(msg["metadata"])),
        pack(date_to_str(msg.get("content", {}))),
    ]
    to_send = []
    if address:
        to_send.append(address)
    to_send += [DELIM, sign(message, key)] + message
    return to_send


async def receive_message(
    sock: Socket, timeout: float = float("inf")
) -> Tuple[List[bytes], dict[str, Any]] | None:
    timeout *= 1000  # in ms
    ready = await sock.poll(timeout)
    if ready:
        msg_list = await sock.recv_multipart()
        idents, msg_list = feed_identities(msg_list)
        return idents, deserialize(msg_list)
    return None


def send_message(
    msg: dict[str, Any],
    sock: Socket,
    key: str,
    address: bytes = b"",
    buffers: List | None = None,
) -> None:
    to_send = serialize(msg, key, address)
    buffers = buffers or []
    for buf in buffers:
        if isinstance(buf, memoryview):
            view = buf
        else:
            view = memoryview(buf)
        assert view.contiguous
    to_send += buffers
    sock.send_multipart(to_send, copy=True)


def pack(obj: dict[str, Any]) -> bytes:
    return jsonapi.dumps(obj)


def unpack(s: bytes) -> dict[str, Any]:
    return cast(dict[str, Any], jsonapi.loads(s))


def sign(msg_list: List[bytes], key: str) -> bytes:
    auth = hmac.new(key.encode("ascii"), digestmod=hashlib.sha256)
    h = auth.copy()
    for m in msg_list:
        h.update(m)
    return h.hexdigest().encode()


def str_to_date(obj: dict[str, Any]) -> dict[str, Any]:
    if "date" in obj:
        obj["date"] = dateutil_parse(obj["date"])
    return obj


def deserialize(msg_list: List[bytes]) -> dict[str, Any]:
    message: dict[str, Any] = {}
    header = unpack(msg_list[1])
    message["header"] = str_to_date(header)
    message["msg_id"] = header["msg_id"]
    message["msg_type"] = header["msg_type"]
    message["parent_header"] = str_to_date(unpack(msg_list[2]))
    message["metadata"] = unpack(msg_list[3])
    message["content"] = unpack(msg_list[4])
    message["buffers"] = [memoryview(b) for b in msg_list[5:]]
    return message


async def check_message(sock: Socket) -> list[tuple[Any, int]]:
    return await sock.poll(0)
