import sys
import types
from typing import Optional, cast


def get_traceback(code: str, return_value: bool):
    exc_info = sys.exc_info()
    tb = cast(types.TracebackType, exc_info[2])
    while True:
        if tb.tb_next is None:
            break
        tb = tb.tb_next
    stack = []
    frame: Optional[types.FrameType] = tb.tb_frame
    while True:
        assert frame is not None
        stack.append(frame)
        frame = frame.f_back
        if frame is None:
            break
    stack.reverse()
    traceback = []
    for frame in stack:
        if frame.f_code.co_filename == "<string>":
            lineno = frame.f_lineno - 2
            if return_value and lineno == len(code.splitlines()) + 1:
                lineno -= 1
        else:
            lineno = frame.f_lineno
            with open(frame.f_code.co_filename) as f:
                code = f.read()
        if frame.f_code.co_name == "__async_cell__":
            name = "<module>"
        else:
            name = frame.f_code.co_name
        trace = [f"{frame.f_code.co_filename} in {name} at line {lineno}:"]
        trace.append(code.splitlines()[lineno - 1])
        traceback += trace
    return ["Traceback (most recent call last):"] + traceback
