from __future__ import annotations

import sys
import types
from typing import cast

from colorama import Fore, Style  # type: ignore


def get_traceback(code: str, exception, execution_count: int = 0):
    exc_info = sys.exc_info()
    tb = cast(types.TracebackType, exc_info[2])
    while True:
        if tb.tb_next is None:
            break
        tb = tb.tb_next
    stack = []
    frame: types.FrameType | None = tb.tb_frame
    while True:
        assert frame is not None
        stack.append(frame)
        frame = frame.f_back
        if frame is None:
            break
    stack.reverse()
    traceback = ["Traceback (most recent call last):"]
    for frame in stack:
        filename = frame.f_code.co_filename
        if filename == "<string>":
            filename = f"{Fore.CYAN}Cell{Style.RESET_ALL} {Fore.GREEN}{execution_count}"
            f"{Style.RESET_ALL}"
        else:
            with open(filename) as f:
                code = f.read()
            filename = f"{Fore.CYAN}File{Style.RESET_ALL} {Fore.GREEN}{filename}{Style.RESET_ALL}"
        if frame.f_code.co_name.startswith("__async_cell"):
            name = "<module>"
        else:
            name = frame.f_code.co_name
        trace = [
            f"{filename} in {Fore.CYAN}{name}{Style.RESET_ALL}, {Fore.CYAN}line{Style.RESET_ALL} "
            f"{Fore.GREEN}{frame.f_lineno}{Style.RESET_ALL}:"
        ]
        trace.append(code.splitlines()[frame.f_lineno - 1])
        traceback += trace
    traceback += [f"{Fore.RED}{type(exception).__name__}{Style.RESET_ALL}: {exception.args[0]}"]
    return traceback
