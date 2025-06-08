from typing import Dict, Callable

import comm  # type: ignore

from .comm import Comm


class CommManager(comm.CommManager):
    comms: Dict[str, Comm]
    targets: Dict[str, Callable]

    def __init__(self):
        super().__init__()
        from akernel.kernel import KERNEL, Kernel

        self.kernel: Kernel = KERNEL

    def register_comm(self, comm: Comm) -> str:
        comm_id = comm.comm_id
        comm.kernel = self.kernel
        self.comms[comm_id] = comm
        return comm_id
