from pydantic import BaseModel


class KernelConfig(BaseModel):
    execute_in_thread: bool
