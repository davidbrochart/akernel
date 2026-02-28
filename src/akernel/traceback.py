from __future__ import annotations

import types
from traceback import extract_tb, format_list
from typing import cast

from colorama import Fore, Style  # type: ignore


def get_traceback(code: str, exception, traceback: types.TracebackType, execution_count: int = 0):
    tb = traceback
    stack = []
    while True:
        frame = tb.tb_frame
        stack.append(frame)
        tb = tb.tb_next
        if tb is None:
            break
    #stack.reverse()
    traceback = ["Traceback (most recent call last):"]
    get_frame = False
    for frame in stack:
        if frame.f_code.co_name.startswith("__async_cell"):
            name = "<module>"
            get_frame = True
        else:
            name = frame.f_code.co_name
        if get_frame:
            filename = frame.f_code.co_filename
            if filename == "<string>":
                filename = f"{Fore.CYAN}Cell{Style.RESET_ALL} {Fore.GREEN}{execution_count}"
                f"{Style.RESET_ALL}"
            else:
                with open(filename) as f:
                    code = f.read()
                filename = f"{Fore.CYAN}File{Style.RESET_ALL} {Fore.GREEN}{filename}{Style.RESET_ALL}"
            trace = [
                f"{filename} in {Fore.CYAN}{name}{Style.RESET_ALL}, {Fore.CYAN}line{Style.RESET_ALL} "
                f"{Fore.GREEN}{frame.f_lineno}{Style.RESET_ALL}:"
            ]
            trace.append(code.splitlines()[frame.f_lineno - 1])
            traceback += trace
    traceback += [f"{Fore.RED}{type(exception).__name__}{Style.RESET_ALL}: {exception.args[0]}"]
    return traceback
