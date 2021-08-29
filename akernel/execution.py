from typing import List, Dict, Tuple, Any, Optional

from colorama import Fore, Style  # type: ignore

from .code import Transform
from .traceback import get_traceback


def pre_execute(
    code: str,
    globals_: Dict[str, Any],
    locals_: Dict[str, Any],
    execution_count: int = 0,
    react: bool = False,
) -> Tuple[List[str], Optional[SyntaxError]]:
    traceback = []
    exception = None

    try:
        async_bytecode = Transform(code, react).get_async_bytecode()
        exec(async_bytecode, globals_, locals_)
    except SyntaxError as e:
        exception = e
        filename = exception.filename
        if filename == "<unknown>":
            filename = f"{Fore.CYAN}Cell{Style.RESET_ALL} {Fore.GREEN}{execution_count}"
            f"{Style.RESET_ALL}"
        else:
            filename = f"{Fore.CYAN}File{Style.RESET_ALL} {Fore.GREEN}{filename}"
            f"{Style.RESET_ALL}"
        assert exception.text is not None
        assert exception.offset is not None
        traceback = [
            f"{filename}, {Fore.CYAN}line{Style.RESET_ALL} {Fore.GREEN}{exception.lineno}"
            f"{Style.RESET_ALL}:",
            f"{Fore.RED}{exception.text.rstrip()}{Style.RESET_ALL}",
            (exception.offset - 1) * " " + "^",
            f"{Fore.RED}{type(exception).__name__}{Style.RESET_ALL}: "
            f"{exception.args[0]}",
        ]

    return traceback, exception


async def execute(
    code: str, globals_: Dict[str, Any], locals_: Dict[str, Any], react: bool = False
) -> Tuple[Any, List[str], bool]:
    result = None
    interrupted = False
    traceback, exception = pre_execute(code, globals_, locals_, react=react)
    if traceback:
        return result, traceback, interrupted

    try:
        result = await locals_["__async_cell__"]()
    except KeyboardInterrupt:
        interrupted = True
    except Exception as e:
        traceback = get_traceback(code, e)

    return result, traceback, interrupted
