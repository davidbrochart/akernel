import linecache
import sys
import threading

import pytest
from rich.text import Text

from akernel.execution import prepare_cell
from akernel.traceback import get_traceback


def render(code, namespace=None):
    namespace = {} if namespace is None else namespace
    try:
        exec(compile(code, "<cell-0>", "exec"), namespace)  # noqa: S102 - test cell execution
    except BaseException as exc:  # noqa: BLE001 - render arbitrary errors, including interrupts
        lines = get_traceback(code, exc, exc.__traceback__, source_map={"<cell-0>": code})
        return lines, Text.from_ansi("\n".join(lines)).plain
    raise AssertionError("Code did not raise")


def test_source_context_without_global_handlers_or_output(capsys):
    exception_hook = sys.excepthook
    thread_hook = threading.excepthook
    code = "private_value = 'do not display this local'\nnumerator = 1\ndenominator = 0\nnumerator / denominator"
    lines, text = render(code)
    assert "Cell 1 (<module>):4" in text
    assert "denominator = 0" in text
    assert "numerator / denominator" in text
    assert "ZeroDivisionError: division by zero" in text
    assert "do not display this local" not in text
    assert "execute_cell" not in text
    assert any("\x1b[" in line for line in lines)
    assert not any(key.startswith("akernel-") for key in linecache.cache)
    assert sys.excepthook is exception_hook
    assert threading.excepthook is thread_hook
    assert capsys.readouterr() == ("", "")


def test_explicit_exception_chain():
    _, text = render(
        "try:\n    raise ValueError('original failure')\n"
        "except ValueError as exc:\n    raise RuntimeError('outer failure') from exc"
    )
    assert "ValueError: original failure" in text
    assert "RuntimeError: outer failure" in text
    assert "direct cause" in text


@pytest.mark.skipif(sys.version_info < (3, 11), reason="Exception groups require Python 3.11")
def test_exception_group():
    _, text = render("raise ExceptionGroup('failures', [ValueError('first'), TypeError('second')])")
    assert "ExceptionGroup: failures" in text
    assert "ValueError: first" in text
    assert "TypeError: second" in text
    assert "Sub-exception #1" in text


@pytest.mark.parametrize("code", ["return 1", "value = ("])
def test_syntax_errors_without_complete_location_information(code):
    cell, lines, exc = prepare_cell(code)
    assert cell is None
    assert isinstance(exc, SyntaxError)
    assert "SyntaxError:" in Text.from_ansi("\n".join(lines)).plain


def test_null_bytes_are_reported_as_cell_errors():
    cell, lines, exc = prepare_cell("\0")
    error_type = ValueError if sys.version_info < (3, 11) else SyntaxError
    assert cell is None
    assert isinstance(exc, error_type)
    text = Text.from_ansi("\n".join(lines)).plain
    assert f"{error_type.__name__}:" in text
    assert "null bytes" in text


def test_each_render_uses_its_own_cell_source():
    _, first = render("raise ValueError('first kernel')")
    _, second = render("raise ValueError('second kernel')")
    assert "first kernel" in first
    assert "first kernel" not in second
    assert "second kernel" in second
    assert not any(key.startswith("akernel-") for key in linecache.cache)
