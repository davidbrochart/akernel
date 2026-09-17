from __future__ import annotations

import linecache
from pathlib import Path
from types import TracebackType
from uuid import uuid4

from rich.console import Console
from rich.traceback import Trace, Traceback

_KERNEL_DIRECTORY = str(Path(__file__).parent) + "/"


def get_traceback(
    code: str,
    exception: BaseException,
    tb: TracebackType | None,
    execution_count: int = 0,
    source_map: dict[str, str] | None = None,
) -> list[str]:
    rich_traceback = Traceback.from_exception(
        type(exception),
        exception,
        tb,
        show_locals=False,
        width=100,
        extra_lines=2,
    )
    cached_sources = []
    render_id = uuid4().hex

    def adapt(trace: Trace) -> None:
        for stack in trace.stacks:
            first_cell = next(
                (i for i, frame in enumerate(stack.frames) if frame.filename.startswith("<cell-")),
                None,
            )
            if first_cell is not None:
                stack.frames = stack.frames[first_cell:]
            stack.frames = [
                frame for frame in stack.frames if not frame.filename.startswith(_KERNEL_DIRECTORY)
            ]
            for frame in stack.frames:
                if not frame.filename.startswith("<cell-"):
                    continue
                cell_number = int(frame.filename[6:-1]) + 1
                source = source_map.get(frame.filename, "") if source_map is not None else code
                # Rich skips snippets for angle-bracket filenames. Give this
                # rendering a unique source-cache key without creating files or
                # overwriting another kernel's cell sources.
                filename = f"akernel-{render_id}/cell-{cell_number}.py"
                linecache.cache[filename] = (
                    len(source),
                    None,
                    source.splitlines(keepends=True),
                    filename,
                )
                cached_sources.append(filename)
                frame.filename = filename
                frame.name = f"Cell {cell_number} ({frame.name})"
            syntax = stack.syntax_error
            if syntax is not None and syntax.filename.startswith("<cell-"):
                source = source_map.get(syntax.filename, "") if source_map is not None else code
                lines = source.splitlines()
                if not syntax.line and 0 < syntax.lineno <= len(lines):
                    syntax.line = lines[syntax.lineno - 1]
                syntax.filename = f"Cell {int(syntax.filename[6:-1]) + 1}"
                syntax.msg += f" ({syntax.filename}, line {syntax.lineno})"
            for child in stack.exceptions:
                adapt(child)

    try:
        adapt(rich_traceback.trace)
        console = Console(
            force_terminal=True,
            force_jupyter=False,
            color_system="standard",
            width=100,
        )
        with console.capture() as capture:
            console.print(rich_traceback)
        return capture.get().splitlines()
    finally:
        for filename in cached_sources:
            linecache.cache.pop(filename, None)
