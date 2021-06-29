from ..message import send_message, create_message


def display(*args, raw: bool = False) -> None:
    from akernel.kernel import KERNEL, PARENT_HEADER_VAR

    parent_header = PARENT_HEADER_VAR.get()
    data = args[0]
    msg = create_message(
        "display_data",
        content=dict(data=data, transient={}, metadata={}),
        parent_header=parent_header,
    )
    send_message(msg, KERNEL.iopub_channel, KERNEL.key)


def clear_output() -> None:
    pass
