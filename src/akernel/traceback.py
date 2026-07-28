from __future__ import annotations

import types
from traceback import extract_tb, format_list
from typing import Dict, cast

from colorama import Fore, Style  # type: ignore


def get_traceback(code: str, exception, tb: types.TracebackType, execution_count: int = 0, source_map: Dict[str, str] | None = None):
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
    get_frame = False
    print
    for frame in stack:
        if frame.f_code.co_name.startswith("__async_cell"):
            name = "<module>"
            get_frame = True
        else:
            name = frame.f_code.co_name
        if get_frame:
            filename = frame.f_code.co_filename
            if filename.startswith("<cell-"):
                source = source_map.get(filename, "") if source_map else ""
                display_filename = (
                    f"{Fore.CYAN}Cell{Style.RESET_ALL} {Fore.GREEN}{int(filename[6:-1]) + 1}"
                    f"{Style.RESET_ALL}"
                )
            else:
                with open(filename) as f:
                    source = f.read()
                display_filename = (
                    f"{Fore.CYAN}File{Style.RESET_ALL} {Fore.GREEN}{filename}"
                    f"{Style.RESET_ALL}"
                )
            name = "<module>" if frame.f_code.co_name.startswith("__async_cell") else frame.f_code.co_name
            trace = [
                f"  {display_filename}, "
                f"{Fore.CYAN}line{Style.RESET_ALL} "
                f"{Fore.GREEN}{frame.f_lineno}{Style.RESET_ALL}, "
                f"in {Fore.CYAN}{name}{Style.RESET_ALL}:"
            ]
            if source:
                trace.append("    " + source.splitlines()[frame.f_lineno - 1].lstrip())
            traceback += trace
    traceback += [
        f"{Fore.RED}{type(exception).__name__}{Style.RESET_ALL}: {exception.args[0]}"
    ]
    return traceback
