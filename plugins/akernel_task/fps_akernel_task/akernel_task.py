from __future__ import annotations

from anyio import TASK_STATUS_IGNORED, create_task_group, sleep_forever
from anyio.abc import TaskStatus
from jupyverse_api.kernel import Kernel as _Kernel

from akernel.kernel import Kernel


class AKernelTask(_Kernel):
    def __init__(self, *args, **kwargs):
        super().__init__()

    async def start(self, *, task_status: TaskStatus[None] = TASK_STATUS_IGNORED) -> None:
        async with (
            create_task_group() as self.task_group,
            self._to_shell_send_stream,
            self._to_shell_receive_stream,
            self._from_shell_send_stream,
            self._from_shell_receive_stream,
            self._to_control_send_stream,
            self._to_control_receive_stream,
            self._from_control_send_stream,
            self._from_control_receive_stream,
            self._to_stdin_send_stream,
            self._to_stdin_receive_stream,
            self._from_stdin_send_stream,
            self._from_stdin_receive_stream,
            self._from_iopub_send_stream,
            self._from_iopub_receive_stream,
        ):
            self.kernel = Kernel(
                self._to_shell_receive_stream,
                self._from_shell_send_stream,
                self._to_control_receive_stream,
                self._from_control_send_stream,
                self._to_stdin_receive_stream,
                self._from_stdin_send_stream,
                self._from_iopub_send_stream,
            )
            self.task_group.start_soon(self.kernel.start)
            task_status.started()
            await sleep_forever()

    async def stop(self) -> None:
        self.task_group.cancel_scope.cancel()

    async def interrupt(self) -> None:
        pass
