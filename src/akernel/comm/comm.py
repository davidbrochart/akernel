from __future__ import annotations

from typing import Any, Callable

import comm

from ..message import send_message, create_message


class Comm(comm.base_comm.BaseComm):
    _msg_callback: Callable | None
    comm_id: str
    topic: bytes
    parent_header: dict[str, Any]

    def __init__(self, **kwargs) -> None:
        from akernel.kernel import KERNEL, PARENT_VAR, Kernel

        self.kernel: Kernel = KERNEL
        self.parent_header = PARENT_VAR.get()["header"]
        super().__init__(**kwargs)

    def publish_msg(
        self,
        msg_type: str,
        data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        buffers: list[bytes] | None = None,
        **keys: Any,
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

    def handle_msg(self, msg: dict[str, Any]) -> None:
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


comm.create_comm = Comm
