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
    show_result=None,
    parent_header=None,
) -> Tuple[List[str], Optional[SyntaxError], bool, Tuple]:
    traceback = []
    exception = None
    code_cached = False
    cached = False
    code_hash = None
    inputs_hash = None
    inputs = []
    outputs = []

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
            code_cached = code_hash in cache
            inputs_sha = hashlib.sha256()
            if code_cached:
                print("Code cached")
                inputs = cache[code_hash]["inputs"]
                outputs = cache[code_hash]["outputs"]
                for k in inputs:
                    try:
                        inputs_sha.update(pickle.dumps(globals_[k]))
                    except Exception:
                        print(f"Cannot pickle.dumps {k}")
            else:
                # first time this code is executed, let's infer inputs and outputs
                for k in cell_globals:
                    if k not in outputs:
                        try:
                            inputs_sha.update(pickle.dumps(globals_[k]))
                            inputs.append(k)
                        except Exception:
                            print(f"Cannot pickle.dumps {k}")
            print(f"Inputs = {inputs}")
            print(f"Outputs = {outputs}")
            inputs_hash = inputs_sha.hexdigest()

    if code_cached:
        assert cache is not None
        assert code_hash is not None
        if inputs_hash in cache[code_hash]:
            print("Execution cached")
            cached = True
            for k, v in cache[code_hash][inputs_hash].items():
                if k != "__result__":
                    try:
                        globals_[k] = pickle.loads(v)
                        print(f"Retrieving {k} = {globals_[k]}")
                    except Exception:
                        print(f"Cannot pickle.loads {k}")
            result = cache[code_hash][inputs_hash]["__result__"]
            show_result(result, globals_, parent_header)

    return traceback, exception, cached, (code_hash, inputs_hash, inputs, outputs)


async def execute(
    code: str, globals_: Dict[str, Any], locals_: Dict[str, Any], react: bool = False
) -> Tuple[Any, List[str], bool]:
    result = None
    interrupted = False
    traceback, exception, cached, cell_cache = pre_execute(
        code, globals_, locals_, react=react
    )
    if traceback:
        return result, traceback, interrupted

    try:
        result = await locals_["__async_cell__"]()
    except KeyboardInterrupt:
        interrupted = True
    except Exception as e:
        traceback = get_traceback(code, e)

    return result, traceback, interrupted
