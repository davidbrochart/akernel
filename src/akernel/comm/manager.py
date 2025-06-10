from typing import Dict, Callable, cast

import comm

from .comm import Comm


class CommManager(comm.CommManager):
    comms: dict[str, comm.base_comm.BaseComm]
    targets: Dict[str, Callable]

    def __init__(self) -> None:
        super().__init__()
        from akernel.kernel import KERNEL, Kernel

        self.kernel: Kernel = KERNEL

    def register_comm(self, comm: comm.base_comm.BaseComm) -> str:
        comm = cast(Comm, comm)
        comm_id = comm.comm_id
        comm.kernel = self.kernel
        self.comms[comm_id] = comm
        return comm_id
