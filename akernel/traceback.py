import sys
import types
from typing import Optional, cast

from colorama import Fore, Style  # type: ignore


def get_traceback(code: str, return_value: bool, execution_count: int):
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
        filename = frame.f_code.co_filename
        if filename == "<string>":
            filename = f"{Fore.CYAN}Cell{Style.RESET_ALL} {Fore.GREEN}{execution_count}"
            f"{Style.RESET_ALL}"
            lineno = frame.f_lineno - 2
            if return_value and lineno == len(code.splitlines()) + 1:
                lineno -= 1
        else:
            lineno = frame.f_lineno
            with open(filename) as f:
                code = f.read()
            filename = f"{Fore.CYAN}File{Style.RESET_ALL} {Fore.GREEN}{filename}{Style.RESET_ALL}"
        if frame.f_code.co_name == "__async_cell__":
            name = "<module>"
        else:
            name = frame.f_code.co_name
        trace = [
            f"{filename} in {Fore.CYAN}{name}{Style.RESET_ALL}, {Fore.CYAN}line{Style.RESET_ALL} "
            f"{Fore.GREEN}{lineno}{Style.RESET_ALL}:"
        ]
        trace.append(code.splitlines()[lineno - 1])
        traceback += trace
    return ["Traceback (most recent call last):"] + traceback
