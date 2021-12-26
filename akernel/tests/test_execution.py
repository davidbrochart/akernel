import sys
from textwrap import dedent
import re
from math import sin
from typing import List, Dict, Tuple, Any

import pytest

from akernel.execution import execute


async def run(
    code: str, react: bool = False
) -> Tuple[Any, List[str], bool, Dict[str, Any], Dict[str, Any]]:
    globals_: Dict[str, Any] = {}
    locals_: Dict[str, Any] = {}
    result, traceback, interrupted = await execute(code, globals_, locals_, react=react)
    if "__builtins__" in globals_:
        del globals_["__builtins__"]
    return result, traceback, interrupted, globals_, locals_


def tb_str(traceback: List[str]) -> str:
    colored_tb = "\n".join(traceback)
    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    nocolor_tb = ansi_escape.sub("", colored_tb)
    return nocolor_tb


@pytest.mark.asyncio
async def test_execute_assign(all_modes):
    code = dedent(
        """
        a = 1
        """
    ).strip()
    r, t, i, g, l = await run(code)  # noqa
    assert g == {"a": 1}


@pytest.mark.asyncio
async def test_execute_assign_in_try(all_modes):
    code = dedent(
        """
        try:
            a
        except:
            a = 1
        """
    ).strip()
    r, t, i, g, l = await run(code)  # noqa
    assert g == {"a": 1}


@pytest.mark.asyncio
async def test_execute_invalid_syntax(all_modes):
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
        POINTER
        SyntaxError: invalid syntax
        """
    ).strip()
    if sys.version_info >= (3, 10):
        pointer = "^"
        expected += ". Perhaps you forgot a comma?"
    elif sys.version_info >= (3, 8):
        pointer = "   ^"
    else:
        pointer = "    ^"
    expected = expected.replace("POINTER", pointer)
    assert tb_str(t) == expected


@pytest.mark.asyncio
async def test_execute_not_defined(all_modes):
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
async def test_execute_import_error(all_modes):
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
async def test_execute_async(all_modes):
    code = dedent(
        """
        import asyncio
        await asyncio.sleep(0)
        a = 1
        """
    ).strip()
    r, t, i, g, l = await run(code)  # noqa
    assert g["a"] == 1


@pytest.mark.asyncio
async def test_execute_react_op():
    code = dedent(
        """
        import ipyx, ipywidgets
        a = b + 1
        b = 2
        """
    ).strip()
    r, t, i, g, l = await run(code, react=True)  # noqa
    assert g["b"].v == 2
    assert g["a"].v == 3


@pytest.mark.asyncio
async def test_execute_react_func():
    code = dedent(
        """
        from math import sin
        import ipyx, ipywidgets
        a = sin(b) + 1
        b = 2
        """
    ).strip()
    r, t, i, g, l = await run(code, react=True)  # noqa
    assert g["b"].v == 2
    assert g["a"].v == sin(2) + 1
