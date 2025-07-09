from __future__ import annotations

from fps import Module

from jupyverse_api.kernel import KernelFactory
from jupyverse_api.kernels import Kernels

from .akernel_task import AKernelTask


class AKernelTaskModule(Module):
    async def prepare(self) -> None:
        kernels = await self.get(Kernels)
        kernels.register_kernel_factory("akernel", KernelFactory(AKernelTask))
