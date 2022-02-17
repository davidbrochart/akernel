import hashlib
import pickle
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
    cache: Optional[Dict[str, Any]] = None,
) -> Tuple[List[str], Optional[SyntaxError], bool, Dict[str, Any]]:
    traceback = []
    exception = None
    code_cached = False
    cached = False
    code_hash = None
    inputs_hash = None
    inputs = []
    outputs = []
    result = None

    try:
        transform = Transform(code, react)
        async_bytecode = transform.get_async_bytecode()
        cell_globals = transform.globals
        outputs = list(transform.outputs)
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
    else:
        if cache is not None:
            code_sha = hashlib.sha256()
            code_sha.update(code.encode())
            code_hash = code_sha.hexdigest()
            for k in cache.keys():
                if k.startswith(code_hash):
                    code_cached = True
                    break
            inputs_sha = hashlib.sha256()
            if code_cached:
                # print("Code cached")
                inputs = cache[f"{code_hash}inputs"]
                outputs = cache[f"{code_hash}outputs"]
                for k in inputs:
                    try:
                        inputs_sha.update(pickle.dumps(globals_[k]))
                    except Exception:
                        # print(f"Cannot pickle.dumps {k}")
                        pass
            else:
                # first time this code is executed, let's infer inputs
                for k in cell_globals:
                    if k not in outputs:
                        # could be an input
                        try:
                            inputs_sha.update(pickle.dumps(globals_[k]))
                            inputs.append(k)
                        except Exception:
                            # WARNING: if we can't pickle it, we say it's not an input
                            # which might not be true
                            # print(f"Cannot pickle.dumps {k}")
                            pass
            # print(f"Inputs = {inputs}")
            # print(f"Outputs = {outputs}")
            inputs_hash = inputs_sha.hexdigest()

    if code_cached:
        assert cache is not None
        assert code_hash is not None
        assert inputs_hash is not None
        hashes = code_hash + inputs_hash
        for k in cache.keys():
            if k.startswith(hashes):
                cached = True
                break
        if cached:
            # print("Execution cached")
            name_i = len(hashes)
            for k in cache.keys():
                if k.startswith(hashes):
                    name = k[name_i:]
                    if name != "__result__":
                        try:
                            globals_[name] = cache[k]
                            # print(f"Retrieving {name} = {globals_[name]}")
                        except Exception:  # as e:
                            # print(e)
                            pass
            result = cache[f"{hashes}__result__"]

    cache_info = {
        "code_hash": code_hash,
        "inputs_hash": inputs_hash,
        "inputs": inputs,
        "outputs": outputs,
        "result": result,
    }
    return traceback, exception, cached, cache_info


def cache_execution(
    cache: Optional[Dict[str, Any]],
    cache_info: Dict[str, Any],
    globals_: Dict[str, Any],
    result: Any,
):
    if cache is not None:
        # this cell execution was not cached, let's cache it
        code_hash = cache_info["code_hash"]
        inputs_hash = cache_info["inputs_hash"]
        new_code = True
        for k in cache.keys():
            if k.startswith(code_hash):
                new_code = False
                break
        if new_code:
            cache[f"{code_hash}inputs"] = cache_info["inputs"]
            cache[f"{code_hash}outputs"] = cache_info["outputs"]
        hashes = code_hash + inputs_hash
        for k in cache_info["outputs"]:
            try:
                cache[hashes + k] = globals_[k]
                # print(f"Caching {k} = {globals_[k]}")
            except Exception:  # as e:
                # print(e)
                pass
        cache[f"{hashes}__result__"] = result


# used in tests (mimic execute_and_finish, finish_execution)
async def execute(
    code: str,
    globals_: Dict[str, Any],
    locals_: Dict[str, Any],
    react: bool = False,
    cache: Optional[Dict[str, Any]] = None,
) -> Tuple[Any, List[str], bool]:
    result = None
    interrupted = False
    traceback, exception, cached, cache_info = pre_execute(
        code, globals_, locals_, react=react, cache=cache
    )
    if traceback:
        return result, traceback, interrupted

    if cached:
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
