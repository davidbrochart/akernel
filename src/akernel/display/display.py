from ..message import create_message, serialize


def display(*args, raw: bool = False) -> None:
    from akernel.kernel import KERNEL, PARENT_VAR

    parent_header = PARENT_VAR.get()["header"]
    data = args[0]
    msg = create_message(
        "display_data",
        content=dict(data=data, transient={}, metadata={}),
        parent_header=parent_header,
    )
    to_send = serialize(msg, KERNEL.key)
    KERNEL.from_iopub_send_stream.send_nowait(to_send)


def clear_output() -> None:
    pass
