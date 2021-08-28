from textwrap import dedent
import re
from typing import List, Dict, Tuple, Any

import pytest

from akernel.execution import execute


async def run(code: str) -> Tuple[Any, List[str], bool, Dict[str, Any], Dict[str, Any]]:
    globals_: Dict[str, Any] = {}
    locals_: Dict[str, Any] = {}
    result, traceback, interrupted = await execute(code, globals_, locals_)
    if "__builtins__" in globals_:
        del globals_["__builtins__"]
    return result, traceback, interrupted, globals_, locals_


def tb_str(traceback: List[str]) -> str:
    colored_tb = "\n".join(traceback)
    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    nocolor_tb = ansi_escape.sub("", colored_tb)
    return nocolor_tb


@pytest.mark.asyncio
async def test_execute_assign():
    code = dedent(
        """
        a = 1
    """
    ).strip()
    r, t, i, g, l = await run(code)  # noqa
    assert g == {"a": 1}


@pytest.mark.asyncio
async def test_execute_invalid_syntax():
    code = dedent(
        """
        ab cd
    """
    ).strip()
    r, t, i, g, l = await run(code)  # noqa
    expected = dedent(
        """
        Cell 0, line 1:
        ab cd
           ^
        SyntaxError: invalid syntax
    """
    ).strip()
    assert tb_str(t) == expected


@pytest.mark.asyncio
async def test_execute_not_defined():
    code = dedent(
        """
        a
    """
    ).strip()
    r, t, i, g, l = await run(code)  # noqa
    expected = dedent(
        """
        Traceback (most recent call last):
        Cell 0 in <module>, line 1:
        a
        NameError: name 'a' is not defined
    """
    ).strip()
    assert tb_str(t) == expected


@pytest.mark.asyncio
async def test_execute_import_error():
    code = dedent(
        """
        from .foo import bar
    """
    ).strip()
    r, t, i, g, l = await run(code)  # noqa
    excepted = dedent(
        """
        Traceback (most recent call last):
        Cell 0 in <module>, line 1:
        from .foo import bar
        KeyError: '__name__' not in globals
    """
    ).strip()
    # FIXME: should be "ImportError: attempted relative import with no known parent package"
    assert tb_str(t) == excepted


@pytest.mark.asyncio
async def test_run_async():
    code = dedent(
        """
        import asyncio
        await asyncio.sleep(0)
        a = 1
    """
    ).strip()
    r, t, i, g, l = await run(code)  # noqa
    assert g["a"] == 1
