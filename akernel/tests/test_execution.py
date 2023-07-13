from __future__ import annotations

import sys
import time
from textwrap import dedent
import re
from math import sin
from typing import List, Dict, Tuple, Any

import pytest

from akernel.execution import execute


async def run(
    code: str,
    globals_: Dict[str, Any] | None = None,
    react: bool = False,
    cache: Dict[str, Any] | None = None,
) -> Tuple[Any, List[str], bool, Dict[str, Any], Dict[str, Any]]:
    if globals_ is None:
        globals_ = {}
    locals_: Dict[str, Any] = {}
    result, traceback, interrupted = await execute(
        code, globals_, locals_, react=react, cache=cache
    )
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
    if sys.version_info >= (3, 11):
        pointer = "   ^"
    elif sys.version_info >= (3, 10):
        pointer = "^"
        expected += ". Perhaps you forgot a comma?"
    elif sys.version_info >= (3, 8):
        pointer = "   ^"
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


@pytest.mark.asyncio
async def test_execute_cache():
    cache = {}
    globals_ = {}
    time_to_sleep = 0.1
    # set inputs
    code_x0 = dedent(
        """
        import time
        x = 0
        """
    ).strip()
    r, t, i, g, l = await run(code_x0, globals_=globals_, cache=cache)  # noqa
    assert g["x"] == 0
    # first run, should not be cached
    code_to_cache = dedent(
        f"""
        time.sleep({time_to_sleep})
        y = x + 1
        2 * y
        """
    ).strip()
    t0 = time.time()
    r, t, i, g, l = await run(code_to_cache, globals_=globals_, cache=cache)  # noqa
    t1 = time.time()
    assert t1 - t0 > time_to_sleep
    assert g["y"] == 1
    assert r == 2
    # same inputs, should be cached
    t0 = time.time()
    r, t, i, g, l = await run(code_to_cache, globals_=globals_, cache=cache)  # noqa
    t1 = time.time()
    assert t1 - t0 < time_to_sleep
    assert g["y"] == 1
    assert r == 2
    # change inputs
    code_x1 = dedent(
        """
        x = 1
        """
    ).strip()
    r, t, i, g, l = await run(code_x1, globals_=globals_, cache=cache)  # noqa
    assert g["x"] == 1
    # inputs changed, should not be cached
    t0 = time.time()
    r, t, i, g, l = await run(code_to_cache, globals_=globals_, cache=cache)  # noqa
    t1 = time.time()
    assert t1 - t0 > time_to_sleep
    assert g["y"] == 2
    assert r == 4
    # same inputs, should be cached
    t0 = time.time()
    r, t, i, g, l = await run(code_to_cache, globals_=globals_, cache=cache)  # noqa
    t1 = time.time()
    assert t1 - t0 < time_to_sleep
    assert g["y"] == 2
    assert r == 4
    # back to first inputs
    r, t, i, g, l = await run(code_x0, globals_=globals_, cache=cache)  # noqa
    assert g["x"] == 0
    # known inputs, should be cached
    t0 = time.time()
    r, t, i, g, l = await run(code_to_cache, globals_=globals_, cache=cache)  # noqa
    t1 = time.time()
    assert t1 - t0 < time_to_sleep
    assert g["y"] == 1
    assert r == 2
