import pytest
from anyio import create_memory_object_stream, create_task_group, fail_after

from akernel.kernel import Kernel
from akernel.message import create_message, deserialize, feed_identities, serialize


@pytest.mark.anyio
@pytest.mark.parametrize("execute_in_thread", [False, True])
async def test_interrupt_and_shutdown(anyio_backend, execute_in_thread):
    streams = [create_memory_object_stream(100) for _ in range(7)]
    kernel = Kernel(
        streams[0][1],
        streams[1][0],
        streams[2][1],
        streams[3][0],
        streams[4][1],
        streams[5][0],
        streams[6][0],
        execute_in_thread=execute_in_thread,
    )

    async def receive(channel):
        frames = await streams[channel][1].receive()
        return deserialize(feed_identities(frames)[1])

    async def execute(code):
        request = create_message("execute_request", content={"code": code, "allow_stdin": True})
        await streams[0][0].send(serialize(request, kernel.key))
        return request["header"]["msg_id"]

    try:
        with fail_after(5):
            async with create_task_group() as tasks:
                tasks.start_soon(kernel.start)
                try:
                    for _ in range(2):
                        await receive(6)
                    first = await execute("import anyio\nprint('ready')\nawait anyio.sleep(60)")
                    while (await receive(6))["header"]["msg_type"] != "stream":
                        pass
                    kernel.interrupt()
                    reply = await receive(1)
                    assert reply["parent_header"]["msg_id"] == first
                    assert reply["content"]["status"] == "error"
                    second = await execute("1 + 2")
                    reply = await receive(1)
                    assert reply["parent_header"]["msg_id"] == second
                    assert reply["content"]["status"] == "ok"
                finally:
                    kernel.stop_event.set()
    finally:
        for pair in streams:
            for stream in pair:
                stream.close()
