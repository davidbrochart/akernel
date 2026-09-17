from __future__ import annotations

import inspect
import re
from textwrap import dedent
from typing import Any

import pytest

from akernel.execution import compile_cell, execute_cell, prepare_cell
from akernel.traceback import get_traceback


async def run(
    code: str,
    globals_: dict[str, Any] | None = None,
) -> tuple[Any, list[str], bool, dict[str, Any]]:
    if globals_ is None:
        globals_ = {}
    result, interrupted = None, False
    cell, traceback, _exception = prepare_cell(code)
    if cell is not None:
        try:
            result = await execute_cell(cell, globals_)
        except KeyboardInterrupt:
            interrupted = True
        except Exception as exc:  # noqa: BLE001 - exercise arbitrary cell errors
            traceback = get_traceback(code, exc, exc.__traceback__, source_map={"<cell-0>": code})
    if "__builtins__" in globals_:
        del globals_["__builtins__"]
    return result, traceback, interrupted, globals_


def tb_str(traceback: list[str]) -> str:
    colored_tb = "\n".join(traceback)
    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    nocolor_tb = ansi_escape.sub("", colored_tb)
    return nocolor_tb


async def test_execute_assign():
    code = dedent(
        """
        a = 1
        """
    ).strip()
    r, t, i, g = await run(code)  # noqa
    assert g == {"a": 1}


async def test_execute_assign_in_try():
    code = dedent(
        """
        try:
            a
        except:
            a = 1
        """
    ).strip()
    r, t, i, g = await run(code)  # noqa
    assert g == {"a": 1}


async def test_execute_invalid_syntax():
    code = dedent(
        """
        ab cd
        """
    ).strip()
    r, t, i, g = await run(code)  # noqa
    text = tb_str(t)
    assert "SyntaxError: invalid syntax" in text
    assert "Cell 1, line 1" in text
    assert "ab cd" in text
    assert "▲" in text


async def test_execute_not_defined():
    code = dedent(
        """
        a
        """
    ).strip()
    r, t, i, g = await run(code)  # noqa
    text = tb_str(t)
    assert "Cell 1 (<module>):1" in text
    assert "NameError: name 'a' is not defined" in text


async def test_execute_import_error():
    code = dedent(
        """
        from .foo import bar
        """
    ).strip()
    r, t, i, g = await run(code)  # noqa
    text = tb_str(t)
    assert "Cell 1 (<module>):1" in text
    assert "from .foo import bar" in text
    assert "KeyError:" in text
    assert "'__name__' not in globals" in text


async def test_execute_async():
    code = dedent(
        """
        import anyio
        await anyio.sleep(0)
        a = 1
        """
    ).strip()
    r, t, i, g = await run(code)  # noqa
    assert g["a"] == 1


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("", None),
        ("# only a comment", None),
        ("value = 3", None),
        ("value = 3\nvalue + 4", 7),
        ("if True:\n    value = 3\nvalue", 3),
        ("for i in range(3):\n    value = i\nvalue", 2),
        ("a, b = (2, 3)\n[a * i for i in range(b)]", [0, 2, 4]),
        ("class Item:\n    value = 3\nitem = Item()\nitem.value", 3),
        ("value = 3\ndef read():\n    return value\nread()", 3),
        ("def update():\n    global value\n    value = 4\nupdate()\nvalue", 4),
        ("def local():\n    hidden = 1\nlocal()\n'hidden' in globals()", False),
        ("locals() is globals()", True),
        ("from anyio import sleep\nawait sleep(0)\n42", 42),
        ("async def value():\n    return 42\nawait value()", 42),
        (
            "from anyio import create_task_group\nasync with create_task_group():\n    value = 3\nvalue",
            3,
        ),
        ("async def items():\n    yield 3\nvalues = [i async for i in items()]\nvalues", [3]),
        ("from __future__ import annotations\nx: MissingType\n__annotations__['x']", "MissingType"),
    ],
)
async def test_native_cell_execution(code, expected):
    namespace = {}
    assert await execute_cell(compile_cell(code), namespace) == expected
    assert not any(name.startswith("__async_cell") for name in namespace)


async def test_final_coroutine_value_is_not_implicitly_awaited():
    namespace = {}
    cell = compile_cell("async def value():\n    raise AssertionError('unexpected await')\nvalue()")
    result = await execute_cell(cell, namespace)
    assert inspect.iscoroutine(result)
    result.close()


async def test_cell_validation_precedes_execution():
    namespace = {}
    with pytest.raises(SyntaxError):
        cell = compile_cell("changed = True\nreturn 3")
        await execute_cell(cell, namespace)
    assert namespace == {}


async def test_shared_functions_see_later_cell_assignments():
    namespace = {}
    await execute_cell(compile_cell("value = 1\ndef read():\n    return value"), namespace)
    result = await execute_cell(compile_cell("value = 2\nread()", task_i=1), namespace)
    assert result == 2


async def test_error_in_previous_cell_function_keeps_source_locations():
    namespace = {}
    first = "def fail():\n    return missing"
    second = "fail()"
    await execute_cell(compile_cell(first, task_i=0), namespace)
    with pytest.raises(NameError) as error:
        await execute_cell(compile_cell(second, task_i=1), namespace)
    traceback = tb_str(
        get_traceback(
            second,
            error.value,
            error.value.__traceback__,
            source_map={"<cell-0>": first, "<cell-1>": second},
        )
    )
    assert "Cell 2 (<module>):1" in traceback
    assert "Cell 1 (fail):2" in traceback
    assert "return missing" in traceback
