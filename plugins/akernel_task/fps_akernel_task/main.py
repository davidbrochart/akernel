from __future__ import annotations

from functools import partial

from fps import Module
from jupyverse_kernel import KernelFactory
from jupyverse_kernels import Kernels

from .akernel_task import AKernelTask
from .models import KernelConfig


class AKernelTaskModule(Module):
    def __init__(self, *args, execute_in_thread: bool = False, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.execute_in_thread = KernelConfig(execute_in_thread=execute_in_thread).execute_in_thread

    async def prepare(self) -> None:
        kernels = await self.get(Kernels)
        kernel_name = "akernel-thread" if self.execute_in_thread else "akernel-task"
        kernels.register_kernel_factory(
            kernel_name,
            KernelFactory(partial(AKernelTask, execute_in_thread=self.execute_in_thread)),
        )


class AKernelThreadTaskModule(Module):
    async def prepare(self) -> None:
        kernels = await self.get(Kernels)
        kernels.register_kernel_factory(
            "akernel-thread", KernelFactory(partial(AKernelTask, execute_in_thread=True))
        )
