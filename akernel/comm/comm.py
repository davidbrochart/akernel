import uuid

from ..message import send_message, create_message


class Comm:
    def __init__(self, target_name="", data={}, metadata={}, buffers=[], **kwargs):
        from ..kernel import KERNEL, PARENT_HEADER_VAR

        self.kernel = KERNEL
        self._closed = True
        self._msg_callback = None
        self._close_callback = None
        self.comm_id = uuid.uuid4().hex
        self.topic = ("comm-" + self.comm_id).encode("ascii")
        self.primary = True
        self.target_name = target_name
        self.target_module = None
        self.parent_header = PARENT_HEADER_VAR.get()
        if self.primary:
            self.open(data=data, metadata=metadata, buffers=buffers)
        else:
            self._closed = False

    def _publish_msg(self, msg_type, data, metadata, buffers, **keys):
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

    def open(self, data, metadata, buffers):
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

    def close(self, data=None, metadata=None, buffers=None, deleting=False):
        if self._closed:
            return
        self._closed = True
        if data is None:
            data = self._close_data
        self._publish_msg(
            "comm_close",
            data=data,
            metadata=metadata,
            buffers=buffers,
        )
        if not deleting:
            self.kernel.comm_manager.unregister_comm(self)

    def send(self, data=[], metadata={}, buffers=[]):
        self._publish_msg("comm_msg", data, metadata, buffers)

    def on_close(self, callback):
        self._close_callback = callback

    def on_msg(self, callback):
        self._msg_callback = callback

    def handle_close(self, msg):
        if self._close_callback:
            self._close_callback(msg)

    def handle_msg(self, msg):
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
