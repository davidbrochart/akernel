import uuid
from typing import Dict, List, Any, Callable, Optional

from ..message import send_message, create_message


class Comm:

    _closed: bool
    _msg_callback: Optional[Callable]
    _close_callback: Optional[Callable]
    comm_id: str
    topic: bytes
    primary: bool
    target_name: str
    target_module: Any
    parent_header: Dict[str, Any]

    def __init__(
        self,
        comm_id: Optional[str] = None,
        primary: Optional[bool] = None,
        target_name: str = "",
        data: Dict[str, Any] = {},
        metadata: Dict[str, Any] = {},
        buffers: List[bytes] = [],
        **kwargs
    ):
        from akernel.kernel import KERNEL, PARENT_HEADER_VAR, Kernel

        self.kernel: Kernel = KERNEL
        self._closed = True
        self._msg_callback = None
        self._close_callback = None
        if comm_id is None:
            self.comm_id = uuid.uuid4().hex
        else:
            self.comm_id = comm_id
        self.topic = ("comm-" + self.comm_id).encode("ascii")
        if primary is None:
            self.primary = True
        else:
            self.primary = primary
        self.target_name = target_name
        self.target_module = None
        self.parent_header = PARENT_HEADER_VAR.get()
        if self.primary:
            self.open(data=data, metadata=metadata, buffers=buffers)
        else:
            self._closed = False

    def _publish_msg(
        self,
        msg_type: str,
        data: Dict[str, Any],
        metadata: Dict[str, Any],
        buffers: List[bytes],
        **keys
    ) -> None:
        msg = create_message(
            msg_type,
            content=dict(data=data, comm_id=self.comm_id, **keys),
            metadata=metadata,
            parent_header=self.parent_header,
        )
        send_message(
            msg,
            self.kernel.iopub_channel,
            self.kernel.key,
            address=self.topic,
            buffers=buffers,
        )

    def __del__(self):
        self.close(deleting=True)

    def open(
        self, data: Dict[str, Any], metadata: Dict[str, Any], buffers: List[bytes]
    ) -> None:
        self.kernel.comm_manager.register_comm(self)
        self._publish_msg(
            "comm_open",
            data=data,
            metadata=metadata,
            buffers=buffers,
            target_name=self.target_name,
            target_module=self.target_module,
        )
        self._closed = False

    def close(
        self,
        data: Dict[str, Any] = {},
        metadata: Dict[str, Any] = {},
        buffers: List[bytes] = [],
        deleting: bool = False,
    ) -> None:
        if self._closed:
            return
        self._closed = True
        self._publish_msg(
            "comm_close",
            data=data,
            metadata=metadata,
            buffers=buffers,
        )
        if not deleting:
            self.kernel.comm_manager.unregister_comm(self)

    def send(
        self,
        data: Dict[str, Any] = {},
        metadata: Dict[str, Any] = {},
        buffers: List[bytes] = [],
    ) -> None:
        self._publish_msg("comm_msg", data, metadata, buffers)

    def on_close(self, callback: Callable) -> None:
        self._close_callback = callback

    def on_msg(self, callback: Callable) -> None:
        self._msg_callback = callback

    def handle_close(self, msg: Dict[str, Any]) -> None:
        if self._close_callback:
            self._close_callback(msg)

    def handle_msg(self, msg: Dict[str, Any]) -> None:
        if self._msg_callback:
            self.kernel.execution_state = "busy"
            msg2 = create_message(
                "status",
                parent_header=msg["header"],
                content={"execution_state": self.kernel.execution_state},
            )
            send_message(msg2, self.kernel.iopub_channel, self.kernel.key)
            self._msg_callback(msg)
            self.kernel.execution_state = "idle"
            msg2 = create_message(
                "status",
                parent_header=msg["header"],
                content={"execution_state": self.kernel.execution_state},
            )
            send_message(msg2, self.kernel.iopub_channel, self.kernel.key)
