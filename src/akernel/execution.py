from __future__ import annotations

import hashlib
import pickle
from typing import List, Dict, Tuple, Any

from colorama import Fore, Style  # type: ignore

from .code import Transform
from .traceback import get_traceback


def pre_execute(
    code: str,
    globals_: Dict[str, Any],
    locals_: Dict[str, Any],
    task_i: int | None = None,
    execution_count: int = 0,
    react: bool = False,
    cache: Dict[str, Any] | None = None,
) -> Tuple[List[str], SyntaxError | None, Dict[str, Any]]:
    traceback = []
    exception = None
    cache_info: Dict[str, Any] = {"cached": False}

    try:
        transform = Transform(code, task_i, react)
        async_bytecode = transform.get_async_bytecode()
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
            f"{Fore.RED}{type(exception).__name__}{Style.RESET_ALL}: {exception.args[0]}",
        ]
    else:
        if cache is not None:
            inputs = transform.globals - transform.outputs
            outputs = transform.outputs
            # print(f"Inputs = {inputs}")
            # print(f"Outputs = {outputs}")
            sha = hashlib.sha256()
            sha.update(code.encode())
            for k in inputs:
                try:
                    sha.update(pickle.dumps(globals_[k]))
                except Exception:
                    # FIXME
                    # cannot pickle inputs, let's abort caching
                    # return traceback, exception, cache_info
                    pass

            hash = sha.hexdigest()
            if transform.has_import:
                # cells that have 'import' must always be executed
                cache_info = {
                    "cached": False,
                    "hash": hash,
                    "outputs": outputs,
                }
                return traceback, exception, cache_info

            # let's see if we have a cache for these particular inputs
            for k in cache.keys():
                if k.startswith(hash):
                    # this cell was cached, no need to run it
                    # let's just load the outputs
                    # print("Execution cached")
                    name_i = len(hash)
                    for k in cache.keys():
                        if k.startswith(hash):
                            name = k[name_i:]
                            if name != "__akernel_cell_result__":
                                globals_[name] = cache[k]
                                # print(f"Retrieving {name} = {globals_[name]}")
                    cache_info = {
                        "cached": True,
                        "result": cache[f"{hash}__akernel_cell_result__"],
                    }
                    return traceback, exception, cache_info

            # this cell was not cached
            cache_info = {
                "cached": False,
                "hash": hash,
                "outputs": outputs,
            }

    return traceback, exception, cache_info


def cache_execution(
    cache: Dict[str, Any] | None,
    cache_info: Dict[str, Any],
    globals_: Dict[str, Any],
    result: Any,
):
    if cache is not None:
        # this cell execution was not cached, let's cache it
        assert not cache_info["cached"]
        hash = cache_info["hash"]
        cache_error = False
        # let's store the outputs
        for k in cache_info["outputs"]:
            try:
                cache[hash + k] = globals_[k]
                # print(f"Caching {k} = {globals_[k]}")
            except Exception:
                cache_error = True
                break
        if cache_error:
            for k in cache_info["outputs"]:
                try:
                    del cache[hash + k]
                except Exception:
                    break
        cache[f"{hash}__akernel_cell_result__"] = result


# used in tests (mimic execute_and_finish, finish_execution)
async def execute(
    code: str,
    globals_: Dict[str, Any],
    locals_: Dict[str, Any],
    react: bool = False,
    cache: Dict[str, Any] | None = None,
) -> Tuple[Any, List[str], bool]:
    result = None
    interrupted = False
    traceback, exception, cache_info = pre_execute(
        code, globals_, locals_, react=react, cache=cache
    )
    if traceback:
        return result, traceback, interrupted

    if cache_info["cached"]:
        result = cache_info["result"]
    else:
        try:
            result = await locals_["__async_cell__"]()
        except KeyboardInterrupt:
            interrupted = True
        except Exception as e:
            traceback = get_traceback(code, e)
        else:
            cache_execution(cache, cache_info, globals_, result)

    return result, traceback, interrupted
